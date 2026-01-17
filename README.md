# Landlord Command Centre

CLI tool for UK landlords to manage property compliance.

## Features

- Track properties and tenancies
- Auto-generate compliance timelines
- Parse tenancy agreement PDFs (coming soon)
- Validate against UK landlord regulations

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database
python main.py init

# Add a property
python main.py property add

# Add a tenancy
python main.py tenancy add 1

# List tenancies
python main.py tenancy list

# Show tenancy details
python main.py tenancy show 1
```

## Commands

```
landlord init                    Initialize database
landlord property add            Add a property
landlord property list           List all properties
landlord property show <id>      Show property details
landlord tenancy add <prop_id>   Add tenancy to property
landlord tenancy list [--active] List tenancies
landlord tenancy show <id>       Show tenancy details
```

## Run on Replit

[![Run on Replit](https://replit.com/badge/github/Bigdork69/landlord-command-centre)](https://replit.com/github/Bigdork69/landlord-command-centre)

Click the button above or import from GitHub URL:
`https://github.com/Bigdork69/landlord-command-centre`
