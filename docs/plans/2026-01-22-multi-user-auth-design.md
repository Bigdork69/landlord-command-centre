# Multi-User Authentication Design

## Overview

Transform the Landlord Command Centre from a single-user local app into a multi-user web application with user registration, login, and per-user data isolation.

## Target Users

Small private group - the owner plus a few other landlords they know personally. Open registration (anyone with the URL can sign up).

## Hosting

**Platform:** Railway
- Free tier sufficient for ~10 users
- HTTPS automatic
- PostgreSQL database included
- Global accessibility
- Auto-deploy from GitHub

---

## 1. User Authentication

### Registration Flow
1. User visits site → clicks "Register"
2. Enters: email, password, name
3. Password hashed with bcrypt, stored in `users` table
4. Email becomes their reminder address automatically
5. Redirected to dashboard

### Login Flow
1. Email + password → validated against database
2. Session cookie created (Flask-Login)
3. Session lasts 30 days (remember me)

### Password Reset
1. "Forgot password" → enter email
2. Receive reset link via Resend API
3. Link valid for 1 hour, single use

### User Data Model
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2. Database Changes

### Tables Requiring `user_id`
- `properties` - each user has their own properties
- `tenancies` - linked to user's properties
- `certificates` - linked to user's properties
- `compliance_events` - linked to user's tenancies/properties
- `served_documents` - linked to user's tenancies
- `sent_reminders` - track what's been sent to whom

### Tables Removed
- `email_settings` - email comes from user account instead

### Query Pattern
Every database query adds user filtering:
```python
# Before
def list_properties():
    return db.execute("SELECT * FROM properties")

# After
def list_properties(user_id):
    return db.execute("SELECT * FROM properties WHERE user_id = ?", user_id)
```

### Database Migration
- Switch from SQLite to PostgreSQL (better for concurrent users)
- Migration script moves existing data to owner's account

---

## 3. UI Changes

### New Pages
- `/login` - email + password form
- `/register` - email + password + name form
- `/forgot-password` - email form to request reset
- `/reset-password/<token>` - new password form
- `/account` - replaces settings page

### Navigation Changes
- Header shows: user's name + "Logout" button
- No more separate Settings page for email configuration

### Protected Routes
- All existing routes require login
- Unauthenticated access → redirect to `/login`
- After login → redirect to dashboard

### Account Page
- View/edit name
- View email (read-only for simplicity)
- Change password
- "Upcoming reminders" preview

### Reminder Emails
- Sent to user's registered email automatically
- No configuration needed

---

## 4. Security

- HTTPS via Railway (automatic)
- Passwords hashed with bcrypt
- Session cookies: HTTP-only, secure flag
- CSRF protection via Flask-WTF
- Rate limiting on login endpoint

---

## 5. Implementation

### New Dependencies
```
flask-login
flask-wtf
bcrypt
psycopg2-binary
```

### Files to Modify
- `database.py` - add users table, add `user_id` to all queries
- `models.py` - add User model
- `app.py` - add auth routes, protect routes, pass `user_id` everywhere
- `config.py` - support `DATABASE_URL` for PostgreSQL
- `services/notifications.py` - loop through all users for reminders

### New Files
- `templates/login.html`
- `templates/register.html`
- `templates/forgot_password.html`
- `templates/reset_password.html`
- `templates/account.html`

### Migration Path
1. Build auth system locally with SQLite
2. Test everything works
3. Create Railway project + PostgreSQL
4. Deploy and migrate existing data
