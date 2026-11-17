# Open Chrome and Compose Gmail Email

## Executive Overview
Opens Google Chrome browser, navigates to Gmail inbox, and sets up a new email composition with recipient, subject, and body fields ready for use.

## Environment & Requirements
- **Required Capabilities:** `desktop_tools`, `browser`, `email_compose`
- **System Dependencies:** Google Chrome, Gmail account access
- **Input Parameters:**
  - `recipient_email`: Email address of the recipient (required, string)
  - `email_subject`: Subject line for the email (required, string)
  - `email_body`: Email body content (required, string)
  - `send_email`: Flag to send the email after composition (optional, boolean)

---

## Pre-checks
- Verify Chrome is accessible via taskbar or keyboard shortcut
- Confirm Gmail is logged in and active in Chrome
- Ensure email compose window is available

---

## Step-by-Step Execution Plan

### Step 1: Open Chrome Browser
1. Press Windows key and select Chrome icon from taskbar
2. Wait for Chrome to launch (3 seconds)
3. Verify Chrome is in foreground

```python
# Open Chrome using keyboard shortcut and open new tab
press_keyboard_buttons(shortcut=["ctrl","t"], app_name="Chrome", reason="Open Chrome browser to the home page", wait=3)
```

### Step 2: Navigate to Gmail
1. Locate Gmail tab in Chrome tab bar
2. Click on the Gmail tab to switch to Gmail view
3. Wait for Gmail inbox to load (2 seconds)

```python
# Click on Gmail tab
left_click(coordinates=[110, 58], reason="Click on the Gmail tab to navigate to Gmail", wait=2)
```

### Step 3: Compose New Email
1. Click the "Compose" button in Gmail
2. Wait for compose window to open (2 seconds)

```python
# Click Compose button
left_click(coordinates=[73, 177], reason="Click the Compose button to create a new email", wait=2)
```

### Step 4: Add Recipient Email Address
1. Click on the Recipients field (To field)
2. Type the recipient email address

```python
# Click and type recipient email
left_click(coordinates=[731, 421], reason="Click on the Recipients field in the Gmail compose window", wait=2)
type_text(text=recipient_email, textbox_coordinates=[744, 421], reason="Type the recipient email address correctly in the To field", wait=2)
```

### Step 5: Add Email Subject (Optional)
1. Click on the Subject line field
2. Type the email subject

```python
# Click and type subject
left_click(coordinates=[731, 480], reason="Click on the Subject line field", wait=2)
type_text(text=email_subject, textbox_coordinates=[744, 480], reason="Type the email subject", wait=2)
```

### Step 6: Add Email Body Content
1. Click in the email body text area
2. Type the email body content

```python
# Click and type email body
left_click(coordinates=[728, 507], reason="Click in the email body text area to focus it", wait=2)
type_text(text=email_body, textbox_coordinates=[728, 507], reason="Type the email body content", wait=2)
```

### Step 7: Send Email (Optional)
1. Verify recipient, subject, and body are correct
2. Click the Send button

```python
# Send the email
left_click(coordinates=[689, 900], reason="Click the Send button to send the email", wait=2)
```

---

## Shortcuts
- **Quick Gmail Access:** Press `Alt + G` or `Ctrl + Shift + M` (if supported)
- **Send Email Shortcut:** `Ctrl + ;` (keyboard send shortcut)
- **Undo Last Action:** `Ctrl + Z`
- **Close Compose Window:** `Esc` or clicking the X button