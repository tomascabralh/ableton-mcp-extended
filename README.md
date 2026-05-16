# AbletonMCP - Ableton Live Model Context Protocol Integration

AbletonMCP connects Ableton Live to Claude AI through the Model Context Protocol (MCP), allowing Claude to directly interact with and control Ableton Live. This integration enables prompt-assisted music production, track creation, and Live session manipulation.

> **This is a fork** of [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) with additional tools (`delete_track`, `delete_clip`, `batch`, `create_clip_with_notes`, `create_track_with_instrument`) and latency fixes on top of the original.

## How it works — two pieces, both required

AbletonMCP is **not a single install**. There are two components that run in separate processes and talk to each other over a TCP socket on `localhost:9877`:

```
┌──────────────────┐    stdio    ┌─────────────────┐   TCP 9877   ┌────────────────────┐
│ Claude Desktop / │ ──────────► │  MCP server     │ ───────────► │  Ableton Live      │
│ Cursor           │             │  (your machine) │              │  + Remote Script   │
└──────────────────┘             └─────────────────┘              └────────────────────┘
```

1. **The MCP server** runs locally on your machine (launched by Claude Desktop / Cursor via `uvx ableton-mcp`). This is the thing that exposes the MCP tools.
2. **The Remote Script** runs *inside* Ableton Live, as an Ableton "Control Surface". It listens on port 9877 and actually executes the commands against the Live API.

**You have to set up both.** Installing only the MCP server won't do anything — without the Remote Script loaded in Ableton, the server has nothing to talk to. The installation below is structured as two steps for this reason.

### Join the Community

Give feedback, get inspired, and build on top of the MCP: [Discord](https://discord.gg/3ZrMyGKnaU). Original integration by [Siddharth](https://x.com/sidahuj).

## Features

- **Two-way communication**: Connect Claude AI to Ableton Live through a socket-based server
- **Track manipulation**: Create, modify, and manipulate MIDI and audio tracks
- **Instrument and effect selection**: Claude can access and load the right instruments, effects and sounds from Ableton's library
- **Clip creation**: Create and edit MIDI clips with notes
- **Session control**: Start and stop playback, fire clips, and control transport

## Installation

### Prerequisites

- Ableton Live 10 or newer
- Python 3.10 or newer
- [uv package manager](https://astral.sh/uv)

On Mac:
```
brew install uv
```

Otherwise, install from [uv's official website](https://docs.astral.sh/uv/getting-started/installation/).

⚠️ Do not proceed before installing uv.

### Step 1 — set up the MCP server (on your machine)

The MCP server is what Claude Desktop / Cursor talks to. It's launched on demand via `uvx`; nothing needs to be installed permanently.

#### Option A: Claude Desktop

Go to **Claude → Settings → Developer → Edit Config → `claude_desktop_config.json`** and add:

```json
{
    "mcpServers": {
        "AbletonMCP": {
            "command": "uvx",
            "args": ["ableton-mcp"]
        }
    }
}
```

[Setup video (upstream)](https://youtu.be/iJWJqyVuPS8)

#### Option B: Cursor

**Cursor Settings → MCP**, then paste:

```
uvx ableton-mcp
```

#### Option C: Smithery (Claude Desktop only)

```bash
npx -y @smithery/cli install @ahujasid/ableton-mcp --client claude
```

> ⚠️ Smithery only sets up Step 1 (the MCP server). You **still need to do Step 2** below to install the Remote Script into Ableton — otherwise the server has nothing to talk to.

> ⚠️ Only run **one** instance of the MCP server — Claude Desktop *or* Cursor, not both. They'll both try to grab the single socket connection to Ableton.

### Step 2 — install the Ableton Remote Script (inside Live)

The Remote Script is the piece that runs *inside* Ableton and actually executes commands against the Live API. You install it by copying one file into Ableton's MIDI Remote Scripts folder.

[Setup video (upstream)](https://youtu.be/iJWJqyVuPS8)

1. Download `AbletonMCP_Remote_Script/__init__.py` from this repo.

2. Create a folder named `AbletonMCP` inside Ableton's MIDI Remote Scripts directory, and put the downloaded `__init__.py` inside it. Different OSes and Live versions put this folder in different places — try these:

   **macOS:**
   - Right-click Ableton Live in Applications → *Show Package Contents* → `Contents/App-Resources/MIDI Remote Scripts/`, OR
   - `~/Library/Preferences/Ableton/Live XX/User Remote Scripts/` (replace `XX` with your Live version)

   **Windows:**
   - `C:\Users\<You>\AppData\Roaming\Ableton\Live x.x.x\Preferences\User Remote Scripts\`, OR
   - `C:\ProgramData\Ableton\Live XX\Resources\MIDI Remote Scripts\`, OR
   - `C:\Program Files\Ableton\Live XX\Resources\MIDI Remote Scripts\`

   Final layout (example): `.../MIDI Remote Scripts/AbletonMCP/__init__.py`

3. Launch Ableton Live.
4. Go to **Settings/Preferences → Link, Tempo & MIDI**.
5. In the **Control Surface** dropdown, select **AbletonMCP**.
6. Set **Input** and **Output** to **None**.

> 💡 If you ever edit `AbletonMCP_Remote_Script/__init__.py`, you have to **re-copy it into Ableton's folder and reload the Control Surface** (toggle the dropdown to *None* and back to *AbletonMCP*) for the change to take effect. The repo's working copy is not what Ableton runs.

## Usage

### Starting the Connection

1. Ensure the Ableton Remote Script is loaded in Ableton Live
2. Make sure the MCP server is configured in Claude Desktop or Cursor
3. The connection should be established automatically when you interact with Claude

### Using with Claude

Once the config file has been set on Claude, and the remote script is running in Ableton, you will see a hammer icon with tools for the Ableton MCP.

## Capabilities

- Get session and track information
- Create, rename, and **delete** MIDI tracks
- Create, edit, name, and **delete** clips
- Add notes to MIDI clips
- Load instruments and effects from Ableton's browser
- Control playback — start/stop, fire and stop clips
- Change tempo and other session parameters
- **Batch / composite tools** for write-heavy workflows: `batch` (run many sub-commands in one round-trip), `create_clip_with_notes` (clip + notes in one step), `create_track_with_instrument` (track + name + instrument in one step). Each of these collapses N operations into ~1 Ableton-framework tick instead of N — much faster for building arrangements

## Example Commands

Here are some examples of what you can ask Claude to do:

- "Create an 80s synthwave track" [Demo (upstream)](https://youtu.be/VH9g66e42XA)
- "Create a Metro Boomin style hip-hop beat"
- "Create a new MIDI track with a synth bass instrument"
- "Add reverb to my drums"
- "Create a 4-bar MIDI clip with a simple melody"
- "Get information about the current Ableton session"
- "Load an 808 drum rack into the selected track"
- "Add a jazz chord progression to the clip in track 1"
- "Set the tempo to 120 BPM"
- "Play the clip in track 2"
- "Delete track 3" / "Empty the clip slot at track 2 slot 0"
- "Build a 4-bar drum pattern in one go" (Claude can use `create_clip_with_notes` instead of two separate calls)


## Troubleshooting

- **Connection issues**: Make sure the Ableton Remote Script is loaded, and the MCP server is configured on Claude
- **Timeout errors**: Try simplifying your requests or breaking them into smaller steps
- **Have you tried turning it off and on again?**: If you're still having connection errors, try restarting both Claude and Ableton Live

## Technical Details

### Communication Protocol

The system uses a simple JSON-based protocol over TCP sockets:

- Commands are sent as JSON objects with a `type` and optional `params`
- Responses are JSON objects with a `status` and `result` or `message`

### Limitations & Security Considerations

- Creating complex musical arrangements might need to be broken down into smaller steps
- The tool is designed to work with Ableton's default devices and browser items
- Always save your work before extensive experimentation

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This is a third-party integration and not made by Ableton.
