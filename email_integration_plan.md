# Email Integration Implementation Plan

## Overview
Integrate email alerting into the Supply Watchdog system to send HTML-formatted alerts to multiple recipients via Gmail SMTP with retry logic and threading.

---

## 1. Update `config.py`

### Changes Needed:
Add email configuration properties to the `Config` class to load from `.env`:

```python
# Email settings
SENDER_EMAIL = os.getenv('sender_email')
APP_PASSWORD = os.getenv('app_password')
RECIPIENT_EMAILS = os.getenv('recipient_emails')  # Comma-separated string

@classmethod
def get_recipient_list(cls):
    """Parse comma-separated recipient emails into a list."""
    if cls.RECIPIENT_EMAILS:
        return [email.strip() for email in cls.RECIPIENT_EMAILS.split(',')]
    return []
```

---

## 2. Update `mail_sender_util.py`

### Current Issues:
- Only supports plain text emails
- Only handles one recipient at a time
- No retry mechanism

### Changes Needed:

Add new function with retry logic:
```python
def send_gmail_html_multi(sender_email, app_password, recipient_list, subject, html_body, max_retries=3):
    """
    Send HTML email to multiple recipients via Gmail SMTP with retry logic.

    Args:
        sender_email: Sender email address
        app_password: Gmail app password
        recipient_list: List of recipient email addresses
        subject: Email subject line
        html_body: HTML content for email body
        max_retries: Number of retry attempts (default: 3)

    Returns:
        bool: True if email sent successfully, False otherwise
    """
```

**Implementation details:**
- Use `MIMEText(html_body, 'html')` instead of `'plain'`
- Join recipient list with commas for `msg['To']`
- Use same Gmail SMTP configuration (smtp.gmail.com:587 with TLS)
- **Retry logic**:
  - Total attempts = 1 initial + max_retries (default 3) = 4 total attempts
  - Use a for loop: `for attempt in range(1, max_retries + 2)`
  - If attempt fails, log the error and retry
  - If all attempts fail, return False
  - If any attempt succeeds, return True immediately
- **Logging**:
  - Log each retry attempt
  - Log final failure if all retries exhausted
  - Log success

---

## 3. Create HTML Email Template Generator

### New Function in `watchdog_core.py`:
```python
def generate_html_email(self, payload):
    """Generate HTML email content from watchdog payload."""
```

### HTML Structure:

#### Header Section
- **Subject/Title**: "Supply Watchdog Alert Report"
- **Run ID and Timestamp**
- **Summary Box**: Display total alerts with severity breakdown
  - X CRITICAL alerts (red text/background)
  - Y HIGH alerts (orange text/background)
  - Z MEDIUM alerts (yellow text/background)

#### Expiry Alerts Section
**Title**: "🔴 Expiring Batches"

**Table structure:**
- Grouped by severity (CRITICAL, HIGH, MEDIUM)
- Color-coded rows:
  - CRITICAL: Red background (#ffcccc or similar)
  - HIGH: Orange background (#ffe6cc or similar)
  - MEDIUM: Yellow background (#fff9cc or similar)

**Columns:**
| Severity | Trial | Location | Batch Lot | Material | Expiry Date | Days Left | Quantity | Action |
|----------|-------|----------|-----------|----------|-------------|-----------|----------|--------|

#### Shortfall Predictions Section
**Title**: "📉 Stock Shortfall Predictions"

**Table structure:**
- Same color-coding by severity
- Different columns:

| Severity | Trial | Location | Material | Current Stock | Weekly Usage | Weeks Left | Stockout Date | Action |
|----------|-------|----------|----------|---------------|--------------|------------|---------------|--------|

#### Footer Section
- "This is an automated alert from Supply Watchdog"
- Timestamp of email generation
- Link/reference to check database for full details

### Special Case: No Alerts
If `total_alerts == 0`:
- **Subject**: "Supply Watchdog: No alerts detected"
- **Body**: Simple message saying "All systems normal. No expiry or shortfall alerts detected for today."
- Still show run ID and timestamp

---

## 4. Integrate into `watchdog_core.py`

### Add Threading Support:
```python
import threading
```

### Add New Method (Thread Target):
```python
def _send_email_thread(self, payload):
    """
    Thread target function to send email alerts.
    This runs in a separate thread to avoid blocking the main process.

    Args:
        payload: The JSON payload with all alerts
    """
```

**This method will:**
1. Generate dynamic subject line
2. Generate HTML body
3. Load email configuration
4. Call mail sender utility (which has retry logic built-in)
5. Log success or failure

### Add New Method (Thread Launcher):
```python
def send_email_alerts(self, payload):
    """
    Launch email sending in a separate thread.

    Args:
        payload: The JSON payload with all alerts
    """
```

**This method will:**
- Create a new thread with `_send_email_thread` as target
- Pass payload as argument
- Start the thread using `.start()`
- Return immediately (non-blocking)

### Implementation Steps for `_send_email_thread()`:

1. **Generate dynamic subject line**:
   - If alerts exist: `f"Supply Watchdog Alert: {critical} CRITICAL, {high} HIGH, {medium} MEDIUM"`
   - If no alerts: `"Supply Watchdog: No alerts detected"`

2. **Generate HTML body** by calling `generate_html_email(payload)`

3. **Load email configuration** from Config:
   - sender_email
   - app_password
   - recipient_list (parsed from comma-separated string)

4. **Call mail sender utility**:
   - Use the new `send_gmail_html_multi()` function
   - Pass all recipients
   - Function will handle retries internally (3 retries = 4 total attempts)

5. **Error handling**:
   - Wrap in try-except block
   - If email fails after all retries, log error but don't crash
   - Print success message if sent

### Update `run()` Method:
Add new step after JSON file generation:

```python
# Current steps:
# 1. Check for expiring batches
# 2. Analyze inventory shortfall predictions
# 3. Total alerts detected
# 4. Save findings to database
# 5. Generate JSON payload
# 6. Save JSON to file

# NEW STEP 7:
print("\n7. Sending email alerts in background...")
self.send_email_alerts(payload)
print("✓ Email thread started (sending in background)")
```

**Important**: The main watchdog process will NOT wait for email to complete. It will start the email thread and continue/finish immediately.

---

## 5. Error Handling & Retry Strategy

### Retry Logic (in `mail_sender_util.py`):
```python
for attempt in range(1, max_retries + 2):  # Default: 1, 2, 3, 4
    try:
        # Attempt to send email
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()

        print(f"✓ Email sent successfully on attempt {attempt}")
        return True

    except Exception as e:
        if attempt < max_retries + 1:
            print(f"✗ Attempt {attempt} failed: {e}. Retrying...")
        else:
            print(f"✗ All {max_retries + 1} attempts failed. Final error: {e}")
            return False
```

### Threading Error Handling (in `watchdog_core.py`):
```python
def _send_email_thread(self, payload):
    try:
        # Generate subject, HTML, load config
        # Call send_gmail_html_multi() which handles retries
        success = send_gmail_html_multi(...)

        if success:
            print("✓ Email alerts sent successfully")
        else:
            print("✗ Failed to send email after all retry attempts")

    except Exception as e:
        print(f"✗ Unexpected error in email thread: {e}")
```

### Possible failure scenarios handled:
1. SMTP connection timeout - **Retries 3 times**
2. Authentication failure - **Retries 3 times**
3. Network issues - **Retries 3 times**
4. Gmail blocking/rate limits - **Retries 3 times**
5. Invalid recipient - **Retries 3 times, then fails gracefully**

---

## 6. Threading Benefits

### Why Threading:
1. **Non-blocking**: Watchdog completes immediately, doesn't wait for email
2. **Resilience**: If email takes long time or hangs, doesn't affect watchdog
3. **Performance**: Watchdog can finish and exit/continue while email sends in background
4. **User Experience**: Faster completion of watchdog run

### Threading Behavior:
```
Watchdog Main Thread          Email Thread (Background)
─────────────────────         ──────────────────────────
Detect alerts
Save to database
Generate JSON
Start email thread ────────────> Start sending email
Print "thread started"            ├─ Attempt 1: Failed
Continue/Finish                   ├─ Attempt 2: Failed
Exit                              ├─ Attempt 3: Failed
                                  └─ Attempt 4: Success
                                     Print "email sent"
                                     Thread exits
```

**Note**: If running in scheduler, the scheduler process stays alive, so the email thread can complete. If running manually, Python will wait for all threads to complete before exiting the process.

---

## 7. Testing Checklist

### Unit Tests:
- [ ] Config loads email variables correctly
- [ ] Recipient string splits into list properly
- [ ] HTML generation creates valid HTML
- [ ] Email function retries on failure
- [ ] Email function stops after max retries
- [ ] Threading launches successfully

### Integration Tests:
- [ ] Manual run sends email in background
- [ ] Scheduled run sends email at scheduled time
- [ ] Email contains correct alert data
- [ ] All recipients receive the email
- [ ] HTML renders correctly in Gmail/Outlook
- [ ] Color coding displays properly

### Error Scenarios:
- [ ] Invalid SMTP credentials - retries 3x, logs error, continues
- [ ] No internet connection - retries 3x, logs error, continues
- [ ] Invalid recipient email - retries 3x, logs error, continues
- [ ] Temporary SMTP failure - retries and succeeds on 2nd/3rd attempt

---

## 8. Dependencies

### Required Python packages:
Standard library (already available):
- `smtplib` ✓
- `email.mime.text` ✓
- `email.mime.multipart` ✓
- `threading` ✓

No additional packages needed.

---

## 9. Configuration (.env)

Already added:
```
sender_email=petonic40@gmail.com
app_password=jjmvnhksfznbkcdr
recipient_emails=tableautest36@gmail.com,coolsudz@gmail.com
```

**Note**: The app_password should be a Google App Password, not the regular Gmail password.

---

## 10. Execution Flow

### When `python watchdog_core.py` runs:
```
Start Monitoring Cycle
├── 1. Detect expiry alerts
├── 2. Detect shortfall predictions
├── 3. Count total alerts
├── 4. Save to database
├── 5. Generate JSON payload
├── 6. Save JSON to file
└── 7. Send email alerts (NEW - in background thread)
    ├── Start thread
    ├── Print "thread started"
    └── Continue
Complete (main thread)

Background Email Thread:
├── Generate subject & HTML
├── Load email config
├── Attempt 1: Send email
│   └── If fail, retry
├── Attempt 2: Send email (if needed)
│   └── If fail, retry
├── Attempt 3: Send email (if needed)
│   └── If fail, retry
├── Attempt 4: Send email (if needed)
│   └── If fail, log final error
└── Thread exits
```

### When `python watchdog_scheduler.py` runs:
```
Scheduler Started
├── Run immediately (includes background email thread)
├── Schedule daily at 8:00 AM
└── Each scheduled run (includes background email thread)
```

---

## 11. Color Scheme (Standard)

### Severity Colors:
- **CRITICAL**:
  - Background: `#ffcccc` (light red)
  - Text: `#cc0000` (dark red)

- **HIGH**:
  - Background: `#ffe6cc` (light orange)
  - Text: `#ff6600` (dark orange)

- **MEDIUM**:
  - Background: `#fff9cc` (light yellow)
  - Text: `#cc9900` (dark yellow/gold)

### Table Styling:
- Border: `1px solid #ddd`
- Header background: `#f2f2f2`
- Font: Arial, sans-serif
- Padding: 8-10px for cells

---

## 12. Files to Modify

1. **config.py** - Add email configuration properties
2. **mail_sender_util.py** - Add HTML multi-recipient function with retry logic
3. **watchdog_core.py** - Add threading, email integration methods, and update run()

**Files NOT modified:**
- watchdog_scheduler.py (no changes needed, it calls watchdog_core.run())
- create_watchdog_table.py (no changes needed)
- .env (already updated by user)

---

## 13. Implementation Order

1. Update `config.py` first
2. Update `mail_sender_util.py` second (add retry logic)
3. Update `watchdog_core.py` last (add threading + email methods)
4. Test manual run
5. Test scheduled run
6. Test retry mechanism (disconnect internet temporarily)

---

## 14. Expected Output

### Console (on success):
```
7. Sending email alerts in background...
✓ Email thread started (sending in background)

[Background thread output:]
✓ Email sent successfully on attempt 1
✓ Email alerts sent successfully
```

### Console (with retries):
```
7. Sending email alerts in background...
✓ Email thread started (sending in background)

[Background thread output:]
✗ Attempt 1 failed: [Error]. Retrying...
✗ Attempt 2 failed: [Error]. Retrying...
✓ Email sent successfully on attempt 3
✓ Email alerts sent successfully
```

### Console (all retries failed):
```
7. Sending email alerts in background...
✓ Email thread started (sending in background)

[Background thread output:]
✗ Attempt 1 failed: [Error]. Retrying...
✗ Attempt 2 failed: [Error]. Retrying...
✗ Attempt 3 failed: [Error]. Retrying...
✗ All 4 attempts failed. Final error: [Error]
✗ Failed to send email after all retry attempts
```

### Email Subject Examples:
- `Supply Watchdog Alert: 3 CRITICAL, 7 HIGH, 5 MEDIUM`
- `Supply Watchdog Alert: 0 CRITICAL, 2 HIGH, 1 MEDIUM`
- `Supply Watchdog: No alerts detected`

---

## 15. Retry Configuration

Default: **3 retries = 4 total attempts**

Can be adjusted in the function call if needed:
```python
# Default (3 retries)
send_gmail_html_multi(sender, password, recipients, subject, html)

# Custom (5 retries = 6 total attempts)
send_gmail_html_multi(sender, password, recipients, subject, html, max_retries=5)
```

---

## End of Implementation Plan
