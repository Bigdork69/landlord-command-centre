"""Google Drive integration for syncing property documents."""

import io
import os
import re
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from config import get_config


# OAuth scopes - read-only access to Drive
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# Document type patterns to match filenames
DOCUMENT_PATTERNS = {
    'gas_safety': [
        r'gas\s*safe', r'cp12', r'gas\s*cert', r'landlord.*gas',
    ],
    'eicr': [
        r'eicr', r'electric.*cert', r'electrical.*report', r'eic\b',
    ],
    'epc': [
        r'\bepc\b', r'energy.*cert', r'energy.*perform',
    ],
    'tenancy': [
        r'tenancy', r'ast\b', r'assured.*shorthold', r'rental.*agreement',
        r'lease', r'agreement',
    ],
}


class GoogleDriveService:
    """Service for syncing documents from Google Drive."""

    def __init__(self):
        self.config = get_config()
        self._credentials = None
        self._service = None

    @property
    def client_config(self) -> dict:
        """Get OAuth client configuration."""
        client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
        client_secret = os.environ.get('GOOGLE_CLIENT_SECRET', '')

        if not client_id or not client_secret:
            return None

        return {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/oauth/callback"],
            }
        }

    @property
    def is_configured(self) -> bool:
        """Check if Google Drive API is configured."""
        return self.client_config is not None

    @property
    def credentials_path(self) -> Path:
        """Path to stored credentials."""
        return self.config.database_dir / "google_credentials.json"

    @property
    def is_authenticated(self) -> bool:
        """Check if user has authorized the app."""
        return self.credentials_path.exists()

    def get_auth_url(self, redirect_uri: str) -> str:
        """Get the OAuth authorization URL."""
        if not self.is_configured:
            raise ValueError("Google API not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")

        flow = Flow.from_client_config(
            self.client_config,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )

        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )

        return auth_url

    def handle_callback(self, authorization_response: str, redirect_uri: str) -> bool:
        """Handle OAuth callback and save credentials."""
        if not self.is_configured:
            return False

        try:
            flow = Flow.from_client_config(
                self.client_config,
                scopes=SCOPES,
                redirect_uri=redirect_uri
            )
            flow.fetch_token(authorization_response=authorization_response)

            credentials = flow.credentials

            # Save credentials
            self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.credentials_path, 'w') as f:
                f.write(credentials.to_json())

            self._credentials = credentials
            return True
        except Exception as e:
            print(f"OAuth callback error: {e}")
            return False

    def disconnect(self) -> None:
        """Remove stored credentials."""
        if self.credentials_path.exists():
            self.credentials_path.unlink()
        self._credentials = None
        self._service = None

    def _get_credentials(self) -> Optional[Credentials]:
        """Load stored credentials."""
        if self._credentials:
            return self._credentials

        if not self.credentials_path.exists():
            return None

        try:
            self._credentials = Credentials.from_authorized_user_file(
                str(self.credentials_path), SCOPES
            )
            return self._credentials
        except Exception:
            return None

    def _get_service(self):
        """Get Google Drive API service."""
        if self._service:
            return self._service

        credentials = self._get_credentials()
        if not credentials:
            return None

        self._service = build('drive', 'v3', credentials=credentials)
        return self._service

    def list_folders(self, parent_id: str = 'root') -> list[dict]:
        """List folders in a directory."""
        service = self._get_service()
        if not service:
            return []

        try:
            query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = service.files().list(
                q=query,
                pageSize=100,
                fields="files(id, name)"
            ).execute()

            return results.get('files', [])
        except Exception as e:
            print(f"Error listing folders: {e}")
            return []

    def list_files(self, folder_id: str) -> list[dict]:
        """List PDF files in a folder."""
        service = self._get_service()
        if not service:
            return []

        try:
            query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
            results = service.files().list(
                q=query,
                pageSize=100,
                fields="files(id, name, modifiedTime)"
            ).execute()

            return results.get('files', [])
        except Exception as e:
            print(f"Error listing files: {e}")
            return []

    def download_file(self, file_id: str, destination: Path) -> bool:
        """Download a file from Google Drive."""
        service = self._get_service()
        if not service:
            return False

        try:
            request = service.files().get_media(fileId=file_id)
            destination.parent.mkdir(parents=True, exist_ok=True)

            with open(destination, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            return True
        except Exception as e:
            print(f"Error downloading file: {e}")
            return False

    def identify_document_type(self, filename: str) -> Optional[str]:
        """Identify document type from filename."""
        filename_lower = filename.lower()

        for doc_type, patterns in DOCUMENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, filename_lower):
                    return doc_type

        return None

    def find_root_folder(self, folder_name: str = "Landlord Documents") -> Optional[str]:
        """Find the root folder for landlord documents."""
        service = self._get_service()
        if not service:
            return None

        try:
            # Search for folder by name
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = service.files().list(
                q=query,
                pageSize=10,
                fields="files(id, name)"
            ).execute()

            files = results.get('files', [])
            if files:
                return files[0]['id']

            return None
        except Exception as e:
            print(f"Error finding root folder: {e}")
            return None

    def scan_property_folders(self, root_folder_id: str = None) -> list[dict]:
        """
        Scan Google Drive for property folders and their documents.

        Expected structure:
        Landlord Documents/
        ├── 45 Oak Street/
        │   ├── Gas Safety 2024.pdf
        │   └── EICR.pdf
        └── 12 Maple Road/
            └── EPC.pdf

        Returns list of:
        {
            'folder_name': '45 Oak Street',
            'folder_id': 'xxx',
            'documents': [
                {'name': 'Gas Safety 2024.pdf', 'id': 'yyy', 'type': 'gas_safety'},
                ...
            ]
        }
        """
        if root_folder_id is None:
            root_folder_id = self.find_root_folder()
            if not root_folder_id:
                return []

        results = []

        # List all property folders
        property_folders = self.list_folders(root_folder_id)

        for folder in property_folders:
            folder_info = {
                'folder_name': folder['name'],
                'folder_id': folder['id'],
                'documents': []
            }

            # List PDF files in this folder
            files = self.list_files(folder['id'])

            for file in files:
                doc_type = self.identify_document_type(file['name'])
                folder_info['documents'].append({
                    'name': file['name'],
                    'id': file['id'],
                    'type': doc_type,
                    'modified': file.get('modifiedTime'),
                })

            results.append(folder_info)

        return results

    def match_folder_to_property(self, folder_name: str, properties: list) -> Optional[int]:
        """
        Try to match a folder name to a property.
        Matches by address similarity.
        """
        folder_lower = folder_name.lower().strip()

        for prop in properties:
            # Exact match
            if prop.address.lower().strip() == folder_lower:
                return prop.id

            # Partial match (folder name contained in address or vice versa)
            if folder_lower in prop.address.lower() or prop.address.lower() in folder_lower:
                return prop.id

            # Match by postcode
            if prop.postcode and prop.postcode.lower().replace(' ', '') in folder_lower.replace(' ', ''):
                return prop.id

        return None
