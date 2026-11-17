# Open YouTube in Chrome Browser

## Executive Overview
Opens Google Chrome browser and navigates to YouTube.com using desktop tools. Used when you need to access YouTube content on your desktop without using web search tools. This workflow ensures YouTube loads correctly in the current Chrome window.

---

## Environment & Requirements
- **Required Capabilities:** Desktop tools, mouse click, keyboard input, Chrome browser access
- **System Dependencies:** Windows OS, Google Chrome installed and accessible
- **Input Parameters:** 
  - `target_url`: youtube.com (required)
  - `chrome_window_focus`: Whether Chrome is already open (default: check and focus)

---

## Pre-checks
- Verify Chrome is running (check taskbar or start menu)
- Confirm address bar is accessible for text input
- Ensure system supports keyboard/mouse input in Chrome

---

## Step-by-Step Execution Plan

### Step 1: Launch or Focus Chrome Browser
1. Press Windows key to open start menu
2. Search for "Chrome" or click Chrome icon in taskbar
3. If Chrome is already open, click to bring it to foreground
4. Wait for Chrome window to be fully visible and focused

### Step 2: Focus Chrome Address Bar
1. Click on Chrome's address bar (coordinates: approximately [400, 37])
2. Verify address bar is focused and ready for input
3. Clear any existing text or ensure clean input field

### Step 3: Navigate to YouTube
1. Type URL: `youtube.com` in address bar
2. Press Enter key to navigate to the website
3. Wait 2-3 seconds for YouTube page to load completely

### Step 4: Verify YouTube Loaded Successfully
1. Confirm URL shows `youtube.com` in address bar
2. Verify YouTube homepage displays with video grid layout
3. Confirm no errors or loading indicators remain

---

## Shortcuts
- **Win + R** → Type `chrome.exe` to open Chrome if not running
- **Alt + Tab** to switch between Chrome windows
- **Ctrl + Shift + T** to reopen closed tabs in Chrome
- **Win + D** to show desktop if Chrome window is minimized