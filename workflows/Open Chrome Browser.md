# Open Chrome Browser Workflow

## Executive Overview
Opens Google Chrome browser by pressing Windows key to bring Chrome to foreground if it's running, or launching it if not. This is useful when Chrome needs to be accessed for web browsing, and it's either not visible in the taskbar or needs to be brought to the front.

## Environment & Requirements
- **Required Capabilities:** 
  - `keyboard_press` (Win key)
  - `left_click` (Mouse/Touchscreen)
- **System Dependencies:** Chrome must be installed on the system

---

## Pre-checks
- Verify Chrome is installed on the system (check taskbar or start menu)
- Check if Chrome is already running but hidden (not visible in taskbar)
- Ensure Chrome icon is accessible in the Windows taskbar or start menu

---

## Step-by-Step Execution Plan

### Step 1: Press Windows Key
1. Press Windows key (`Win`) to open the Start menu
   ```bash
   # Execute command
   ```
   - Wait 2 seconds for menu to appear

### Step 2: Click Chrome Icon in Taskbar
1. Click on Chrome icon in Windows taskbar to bring it to foreground
   ```bash
   # Coordinates may vary based on system layout
   ```
   - Wait 3 seconds for Chrome window to appear
   - Verify Chrome is now the active window

---

## Shortcuts
- `Win + R` - Open Run dialog (alternative to start menu)
- `Alt + Tab` - Switch between open windows if Chrome is already running