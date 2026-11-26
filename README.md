# HandControl

Control common Windows window actions with simple hand gestures. HandControl runs in the system tray and starts with gesture control **off**; turn it on only when you want to use your camera.

When enabled, point with your index finger at one of three on-screen targets, hold briefly, then flick down to close, minimise, or maximise/restore the foreground window.

## Features

- System-tray controls and the global `Ctrl+Alt+H` toggle.
- Gesture-driven close, minimise, and maximise/restore actions.
- An aiming guide and target label so you can see which window will be affected.
- Camera capture and hand tracking only while gesture control is enabled.
- Optional hand-skeleton overlay and persistent action targets.
- A standalone Windows executable build script.

## Requirements

- Windows 10 or later.
- Python 3.10, 3.11, or 3.12 (64-bit) to run from source or build the executable.
- A working webcam.

## Run from source

Open PowerShell in the project folder and run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python hand_control.py
```

Use `py -3.11` or `py -3.10` instead if that is the Python version installed on your computer. When the tray icon appears, press **Ctrl+Alt+H** or use the tray menu to enable hand control. The camera is opened only while control is enabled.

## Build the executable

Install Python 3.10, 3.11, or 3.12 (64-bit), then double-click `build_exe.bat` or run it from Command Prompt. The script creates a local virtual environment, installs the dependencies and PyInstaller, and builds:

```text
dist\HandControl.exe
```

The first build downloads the required packages and may take several minutes. The resulting executable is unsigned, so Windows or antivirus software may show a warning.

## Gestures and controls

1. Enable hand control with **Ctrl+Alt+H** or the tray menu.
2. Show your hand to the camera and point with your index finger, keeping the other fingers curled. Targets are on the right side of the screen.
3. Aim at a target: **red** closes, **yellow** minimises, and **green** maximises or restores the current foreground window. The label shows the target window.
4. Hold your aim briefly, then flick your finger sharply downward to confirm.
5. Toggle control off when finished. The camera is released and the overlay is hidden.

The close action sends a normal Windows close request; an application may ask you to save unsaved work. Windows applications running as administrator may require HandControl to be run as administrator as well.

## Command-line options

| Option | Description |
| --- | --- |
| `--on` | Start with hand control enabled. |
| `--camera N` | Select a camera index (default: `0`). |
| `--skeleton` | Draw the detected hand skeleton. |
| `--always-dots` | Keep the action targets visible while control is enabled. |

For example:

```powershell
python hand_control.py --camera 1 --skeleton
```

## Troubleshooting

- **Camera does not open:** Close other apps using the webcam, check Windows camera privacy settings, or try another index with `--camera N`.
- **The global shortcut does not work:** Another application may have registered `Ctrl+Alt+H`; use the tray menu instead.
- **An elevated window cannot be controlled:** Run HandControl with the same or higher privilege level as that application.
- **The executable is flagged by antivirus:** The PyInstaller build is unsigned. Review your security software's warning before choosing whether to allow it.

## Privacy

Hand tracking is performed locally using the installed OpenCV and MediaPipe packages. The application does not send camera frames to a server. The camera is not opened until hand control is enabled.

## License

No license is currently provided. Unless a license is added, all rights remain with the copyright holder and others may not reuse, redistribute, or modify this project.
