# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

# Per-command logging is on the hot path; off by default. Flip to True to trace
# every command in Ableton's log. (log_message has no levels, so we gate manually.)
DEBUG = False

# Arrangement clips are addressed by start beat; match within this tolerance
# because beat positions are floats. Clips on one track can't overlap, so the
# match is unique.
ARRANGEMENT_BEAT_EPSILON = 1e-3

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()

        # Lazy cache for dir(app.browser); fixed for the session.
        self._browser_attrs_cache = None

        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except Exception:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        # No Nagle on a localhost request/response protocol.
        try:
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception as e:
            self.log_message("Could not set TCP_NODELAY: " + str(e))
        buffer = ''  # '' not b'' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        if DEBUG:
                            self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except Exception:
                        # If we can't send the error, the connection is probably dead
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except Exception:
                pass
            self.log_message("Client handler stopped")
    
    def _process_command(self, command):
        """Process a command from the client and return a response"""
        command_type = command.get("type", "")
        params = command.get("params", {})
        
        # Initialize response
        response = {
            "status": "success",
            "result": {}
        }
        
        try:
            # Route the command to the appropriate handler
            if command_type == "get_session_info":
                response["result"] = self._get_session_info()
            elif command_type == "get_track_info":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_info(track_index)
            elif command_type == "get_session_structure":
                response["result"] = self._get_session_structure()
            elif command_type == "get_arrangement_clips":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_arrangement_clips(track_index)
            elif command_type == "get_song_length":
                response["result"] = self._get_song_length()
            elif command_type == "get_sends":
                response["result"] = self._get_sends(params.get("track_index", 0),
                                                      params.get("track_type", "track"))
            elif command_type == "get_return_tracks":
                response["result"] = self._get_return_tracks()
            elif command_type == "get_master_track":
                response["result"] = self._get_master_track()
            # Commands that modify Live's state must run on Ableton's main thread.
            elif command_type in ["create_midi_track", "set_track_name",
                                 "create_clip", "add_notes_to_clip", "set_clip_name",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "delete_track", "delete_clip",
                                 "batch", "create_clip_with_notes",
                                 "create_track_with_instrument",
                                 "insert_clip_in_arrangement", "delete_arrangement_clip",
                                 "duplicate_arrangement_clip", "set_arrangement_loop",
                                 "set_arrangement_record",
                                 "set_track_volume", "set_track_pan",
                                 "set_track_mute", "set_track_solo",
                                 "set_track_arm", "set_send"]:
                response_queue = queue.Queue()

                def main_thread_task():
                    try:
                        result = self._dispatch_state_command(command_type, params)
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        self.log_message("Error in main thread task: " + str(e))
                        self.log_message(traceback.format_exc())
                        response_queue.put({"status": "error", "message": str(e)})

                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    # Already on the main thread — run inline.
                    main_thread_task()

                try:
                    task_response = response_queue.get(timeout=10.0)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for operation to complete"
            elif command_type == "get_browser_item":
                uri = params.get("uri", None)
                path = params.get("path", None)
                response["result"] = self._get_browser_item(uri, path)
            elif command_type == "get_browser_tree":
                category_type = params.get("category_type", "all")
                response["result"] = self.get_browser_tree(category_type)
            elif command_type == "get_browser_items_at_path":
                path = params.get("path", "")
                response["result"] = self.get_browser_items_at_path(path)
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)
        
        return response

    def _dispatch_state_command(self, command_type, params):
        """Run a state-mutating sub-command on the main thread. Used by
        main_thread_task and recursively by _run_batch."""
        if command_type == "create_midi_track":
            return self._create_midi_track(params.get("index", -1))
        elif command_type == "set_track_name":
            return self._set_track_name(params.get("track_index", 0), params.get("name", ""))
        elif command_type == "create_clip":
            return self._create_clip(params.get("track_index", 0),
                                     params.get("clip_index", 0),
                                     params.get("length", 4.0))
        elif command_type == "add_notes_to_clip":
            return self._add_notes_to_clip(params.get("track_index", 0),
                                           params.get("clip_index", 0),
                                           params.get("notes", []))
        elif command_type == "set_clip_name":
            return self._set_clip_name(params.get("track_index", 0),
                                       params.get("clip_index", 0),
                                       params.get("name", ""))
        elif command_type == "set_tempo":
            return self._set_tempo(params.get("tempo", 120.0))
        elif command_type == "fire_clip":
            return self._fire_clip(params.get("track_index", 0),
                                   params.get("clip_index", 0))
        elif command_type == "stop_clip":
            return self._stop_clip(params.get("track_index", 0),
                                   params.get("clip_index", 0))
        elif command_type == "start_playback":
            return self._start_playback()
        elif command_type == "stop_playback":
            return self._stop_playback()
        elif command_type == "load_browser_item":
            return self._load_browser_item(params.get("track_index", 0),
                                           params.get("item_uri", ""))
        elif command_type == "delete_track":
            return self._delete_track(params.get("track_index", 0))
        elif command_type == "delete_clip":
            return self._delete_clip(params.get("track_index", 0),
                                     params.get("clip_index", 0))
        elif command_type == "batch":
            return self._run_batch(params.get("commands", []))
        elif command_type == "create_clip_with_notes":
            return self._create_clip_with_notes(params.get("track_index", 0),
                                                params.get("clip_index", 0),
                                                params.get("length", 4.0),
                                                params.get("notes", []))
        elif command_type == "create_track_with_instrument":
            return self._create_track_with_instrument(params.get("index", -1),
                                                      params.get("name", ""),
                                                      params.get("instrument_uri", ""))
        elif command_type == "insert_clip_in_arrangement":
            return self._insert_clip_in_arrangement(params.get("track_index", 0),
                                                    params.get("start_beat", 0.0),
                                                    params.get("length", 4.0),
                                                    params.get("notes", []))
        elif command_type == "delete_arrangement_clip":
            return self._delete_arrangement_clip(params.get("track_index", 0),
                                                 params.get("start_beat", 0.0))
        elif command_type == "duplicate_arrangement_clip":
            return self._duplicate_arrangement_clip(params.get("track_index", 0),
                                                    params.get("source_start_beat", 0.0),
                                                    params.get("target_start_beat", 0.0))
        elif command_type == "set_arrangement_loop":
            return self._set_arrangement_loop(params.get("start_beat", 0.0),
                                              params.get("end_beat", 0.0),
                                              params.get("enabled", True))
        elif command_type == "set_arrangement_record":
            return self._set_arrangement_record(params.get("enabled", False))
        elif command_type == "set_track_volume":
            return self._set_track_volume(params.get("track_index", 0),
                                          params.get("value", 0.85),
                                          params.get("track_type", "track"))
        elif command_type == "set_track_pan":
            return self._set_track_pan(params.get("track_index", 0),
                                       params.get("value", 0.0),
                                       params.get("track_type", "track"))
        elif command_type == "set_track_mute":
            return self._set_track_mute(params.get("track_index", 0),
                                        params.get("mute", False),
                                        params.get("track_type", "track"))
        elif command_type == "set_track_solo":
            return self._set_track_solo(params.get("track_index", 0),
                                        params.get("solo", False),
                                        params.get("track_type", "track"))
        elif command_type == "set_track_arm":
            return self._set_track_arm(params.get("track_index", 0),
                                       params.get("arm", False))
        elif command_type == "set_send":
            return self._set_send(params.get("track_index", 0),
                                  params.get("send_index", 0),
                                  params.get("value", 0.0),
                                  params.get("track_type", "track"))
        else:
            raise Exception("Unknown state-modifying command: " + command_type)

    def _run_batch(self, commands):
        """Run sub-commands in the current main-thread task; continues past
        per-sub failures."""
        results = []
        for sub in commands:
            sub_type = sub.get("type", "")
            sub_params = sub.get("params", {})
            try:
                sub_result = self._dispatch_state_command(sub_type, sub_params)
                results.append({"ok": True, "type": sub_type, "result": sub_result})
            except Exception as e:
                self.log_message("Batch sub-command '" + sub_type + "' failed: " + str(e))
                results.append({"ok": False, "type": sub_type, "error": str(e)})
        return {"results": results}

    def _create_clip_with_notes(self, track_index, clip_index, length, notes):
        """create_clip + add_notes_to_clip in one task."""
        self._create_clip(track_index, clip_index, length)
        self._add_notes_to_clip(track_index, clip_index, notes)
        return {
            "track_index": track_index,
            "clip_index": clip_index,
            "length": length,
            "note_count": len(notes),
        }

    def _create_track_with_instrument(self, index, name, instrument_uri):
        """create_midi_track + optional rename + load_browser_item, in one task."""
        create_result = self._create_midi_track(index)
        new_index = create_result.get("index")
        if new_index is None:
            raise Exception("Could not determine new track index after create_midi_track")
        if name:
            self._set_track_name(new_index, name)
        instrument_loaded = False
        if instrument_uri:
            load_result = self._load_browser_item(new_index, instrument_uri)
            instrument_loaded = bool(load_result.get("loaded", False))
        final_name = self._song.tracks[new_index].name
        return {
            "track_index": new_index,
            "name": final_name,
            "instrument_loaded": instrument_loaded,
        }

    def _get_browser_attrs(self, app):
        """Cached list of public attribute names on app.browser."""
        if self._browser_attrs_cache is None:
            self._browser_attrs_cache = [
                attr for attr in dir(app.browser) if not attr.startswith('_')
            ]
        return self._browser_attrs_cache

    # Command implementations

    def _group_track_index(self, track, index_by_id=None):
        """Index of a track's immediate parent group in song.tracks, or None.

        Track.group_track is the *direct* parent, so nested groups resolve to the
        immediate enclosing group, not the outermost one.

        Pass index_by_id (id(track) -> index, built once from a single
        song.tracks snapshot) to resolve many tracks in O(1) each instead of an
        O(n) scan per call. The == scan stays as a fallback: Live can hand out a
        distinct proxy wrapper for the same underlying track, so a map miss is
        possible and must not be treated as 'no parent'."""
        group = getattr(track, "group_track", None)
        if group is None:
            return None
        if index_by_id is not None:
            idx = index_by_id.get(id(group))
            if idx is not None:
                return idx
        for i, t in enumerate(self._song.tracks):
            if t == group:
                return i
        return None

    def _get_session_info(self):
        """Get information about the current session"""
        try:
            # One snapshot + id->index map so per-track parent lookups are O(1).
            tracks = list(self._song.tracks)
            index_by_id = {id(t): i for i, t in enumerate(tracks)}
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                },
                # Compact per-track hierarchy so structure is available without N
                # get_track_info calls (see also get_session_structure).
                "tracks": [
                    {
                        "index": i,
                        "name": t.name,
                        "is_group_track": bool(getattr(t, "is_foldable", False)),
                        "is_grouped": getattr(t, "group_track", None) is not None,
                        "group_track_index": self._group_track_index(t, index_by_id),
                    }
                    for i, t in enumerate(tracks)
                ]
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_session_structure(self):
        """Whole track tree in one round-trip: top-level tracks in order, each
        group carrying its children (recursively for nested groups)."""
        tracks = list(self._song.tracks)
        index_by_id = {id(t): i for i, t in enumerate(tracks)}
        nodes = []
        for i, t in enumerate(tracks):
            nodes.append({
                "index": i,
                "name": t.name,
                "is_group_track": bool(getattr(t, "is_foldable", False)),
                "is_midi_track": t.has_midi_input,
                "is_audio_track": t.has_audio_input,
                "children": []
            })
        roots = []
        for i, t in enumerate(tracks):
            parent = self._group_track_index(t, index_by_id)
            if parent is None:
                roots.append(nodes[i])
            else:
                nodes[parent]["children"].append(nodes[i])
        return {"tracks": roots, "track_count": len(tracks)}

    def _track_arrangement_clips(self, track):
        """arrangement_clips for a track, or [] for tracks that can't hold them.
        Live RAISES (RuntimeError) when you read arrangement_clips on Main/Group/
        Return tracks, so getattr's AttributeError-only default can't guard it --
        the same trap as Track.arm (see _get_track_info)."""
        try:
            return list(track.arrangement_clips)
        except Exception:
            return []

    def _find_arrangement_clip(self, track, start_beat):
        """Return the arrangement clip on `track` whose start_time matches
        start_beat within ARRANGEMENT_BEAT_EPSILON. Raises listing the available
        start beats if none match. Arrangement clips on one track can't overlap,
        so the match is unique."""
        clips = self._track_arrangement_clips(track)
        for clip in clips:
            if abs(clip.start_time - start_beat) <= ARRANGEMENT_BEAT_EPSILON:
                return clip
        available = [round(c.start_time, 4) for c in clips]
        raise Exception("No arrangement clip starting at beat {0} (available: {1})".format(
            start_beat, available))

    def _get_song_length(self):
        """Song length in beats: the time of the last event in the Arrangement."""
        return {"length": self._song.last_event_time}

    def _get_arrangement_clips(self, track_index):
        """List the clips on a track's arrangement timeline. MIDI clips include
        their notes (clip-relative times); audio clips report notes=None."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        clips = []
        for clip in self._track_arrangement_clips(track):
            info = {
                "name": clip.name,
                "start_beat": clip.start_time,
                "length": clip.length,
                "is_midi_clip": clip.is_midi_clip,
                "notes": None,
            }
            if clip.is_midi_clip:
                raw = clip.get_notes_extended(0, 128, 0, clip.length)
                info["notes"] = [
                    {
                        "pitch": n.pitch,
                        "start_time": n.start_time,
                        "duration": n.duration,
                        "velocity": n.velocity,
                        "mute": n.mute,
                    }
                    for n in raw
                ]
            clips.append(info)
        return {"track_index": track_index, "clip_count": len(clips), "clips": clips}

    def _find_or_make_empty_slot(self, track_index):
        """Return (slot_index, created_scene_index) for an empty Session clip slot
        on the track. Prefers an existing empty slot; if the track is full, appends
        a scene (one empty slot on every track) and returns its index as
        created_scene_index so the caller can delete it afterward."""
        track = self._song.tracks[track_index]
        for i, slot in enumerate(track.clip_slots):
            if not slot.has_clip:
                return i, None
        self._song.create_scene(-1)
        new_index = len(self._song.scenes) - 1
        return new_index, new_index

    def _insert_clip_in_arrangement(self, track_index, start_beat, length, notes):
        """Create a MIDI clip at start_beat on the track's arrangement timeline
        and optionally fill it with notes (note times are clip-relative).

        The Control Surface LOM has no Track.create_midi_clip (that exists only in
        the Max-for-Live API), and the only way to make an arrangement clip is to
        duplicate an existing one. So we stage a temporary Session clip, fill it,
        duplicate it into the arrangement, then remove the staging clip (and any
        scene we had to add) so Session view is left untouched."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if not track.has_midi_input:
            raise Exception("Track {0} is not a MIDI track".format(track_index))
        if length <= 0:
            raise Exception("Clip length must be greater than 0")

        slot_index, created_scene = self._find_or_make_empty_slot(track_index)
        track = self._song.tracks[track_index]
        slot = track.clip_slots[slot_index]
        try:
            slot.create_clip(length)
            staging = slot.clip
            if notes:
                live_notes = []
                for note in notes:
                    live_notes.append((
                        note.get("pitch", 60),
                        note.get("start_time", 0.0),
                        note.get("duration", 0.25),
                        note.get("velocity", 100),
                        note.get("mute", False),
                    ))
                staging.set_notes(tuple(live_notes))
            arrangement_clip = track.duplicate_clip_to_arrangement(staging, start_beat)
        finally:
            if track.clip_slots[slot_index].has_clip:
                track.clip_slots[slot_index].delete_clip()
            if created_scene is not None:
                self._song.delete_scene(created_scene)

        # duplicate_clip_to_arrangement returns the new clip; locate by start as a
        # fallback.
        if arrangement_clip is None:
            arrangement_clip = self._find_arrangement_clip(track, start_beat)
        return {
            "track_index": track_index,
            "start_beat": arrangement_clip.start_time,
            "length": arrangement_clip.length,
            "name": arrangement_clip.name,
            "note_count": len(notes),
        }

    def _delete_arrangement_clip(self, track_index, start_beat):
        """Remove the arrangement clip starting at start_beat."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        clip = self._find_arrangement_clip(track, start_beat)
        name = clip.name
        track.delete_clip(clip)
        return {"deleted": True, "track_index": track_index,
                "start_beat": start_beat, "name": name}

    def _duplicate_arrangement_clip(self, track_index, source_start_beat, target_start_beat):
        """Copy an arrangement clip from one position to another on the same track."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        source = self._find_arrangement_clip(track, source_start_beat)
        new_clip = track.duplicate_clip_to_arrangement(source, target_start_beat)
        if new_clip is None:
            new_clip = self._find_arrangement_clip(track, target_start_beat)
        return {
            "track_index": track_index,
            "source_start_beat": source_start_beat,
            "target_start_beat": new_clip.start_time,
            "length": new_clip.length,
            "name": new_clip.name,
        }

    def _set_arrangement_loop(self, start_beat, end_beat, enabled):
        """Set the Arrangement loop region and on/off state. Live applies the
        `loop` write asynchronously, so we echo the requested values rather than
        reading the (stale) property back in this same call."""
        if end_beat <= start_beat:
            raise Exception("end_beat ({0}) must be greater than start_beat ({1})".format(
                end_beat, start_beat))
        self._song.loop_start = start_beat
        self._song.loop_length = end_beat - start_beat
        self._song.loop = enabled
        return {
            "loop": bool(enabled),
            "loop_start": start_beat,
            "loop_length": end_beat - start_beat,
        }

    def _set_arrangement_record(self, enabled):
        """Toggle the Arrangement record button (Song.record_mode). The write is
        applied asynchronously, so echo intent instead of re-reading the stale
        property."""
        self._song.record_mode = 1 if enabled else 0
        return {"record_mode": bool(enabled)}

    def _resolve_track(self, track_index, track_type):
        """Resolve a track object from (index, type). track_type is one of
        'track', 'return', 'master'. Raises IndexError / ValueError on bad input."""
        if track_type == "master":
            return self._song.master_track
        if track_type == "return":
            returns = self._song.return_tracks
            if track_index < 0 or track_index >= len(returns):
                raise IndexError("Return track index out of range")
            return returns[track_index]
        if track_type == "track":
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise IndexError("Track index out of range")
            return tracks[track_index]
        raise ValueError("Unknown track_type: " + str(track_type))

    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            # track.arm raises RuntimeError (not AttributeError) on tracks that
            # can't be armed, so getattr can't guard it; use can_be_armed and fall
            # back to None. Other reads here are safe on group tracks.
            is_group_track = bool(getattr(track, "is_foldable", False))
            try:
                arm_state = track.arm if track.can_be_armed else None
            except Exception:
                arm_state = None
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": arm_state,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "sends": self._send_list(track),
                "is_group_track": is_group_track,
                "is_grouped": getattr(track, "group_track", None) is not None,
                "group_track_index": self._group_track_index(track),
                "fold_state": getattr(track, "fold_state", None) if is_group_track else None,
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise
    
    
    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise

    def _delete_track(self, track_index):
        """Delete a track at the given index"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            name = self._song.tracks[track_index].name
            self._song.delete_track(track_index)

            result = {
                "deleted_index": track_index,
                "name": name,
                "track_count": len(self._song.tracks)
            }
            return result
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            
            # Convert note data to Live's format
            live_notes = []
            for note in notes:
                pitch = note.get("pitch", 60)
                start_time = note.get("start_time", 0.0)
                duration = note.get("duration", 0.25)
                velocity = note.get("velocity", 100)
                mute = note.get("mute", False)
                
                live_notes.append((pitch, start_time, duration, velocity, mute))
            
            # Add the notes
            clip.set_notes(tuple(live_notes))
            
            result = {
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise

    def _delete_clip(self, track_index, clip_index):
        """Delete the clip in the given track / clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip_slot.delete_clip()

            result = {
                "deleted": True,
                "track_index": track_index,
                "clip_index": clip_index
            }
            return result
        except Exception as e:
            self.log_message("Error deleting clip: " + str(e))
            raise

    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _set_track_volume(self, track_index, value, track_type):
        """Set a track's volume fader to a raw 0..1 value (server pre-converts dB)."""
        track = self._resolve_track(track_index, track_type)
        v = max(0.0, min(1.0, value))
        track.mixer_device.volume.value = v
        return {"track_index": track_index, "track_type": track_type, "value": v}

    def _set_track_pan(self, track_index, value, track_type):
        """Set a track's pan to a raw -1..1 value (server pre-converts -100..100)."""
        track = self._resolve_track(track_index, track_type)
        v = max(-1.0, min(1.0, value))
        track.mixer_device.panning.value = v
        return {"track_index": track_index, "track_type": track_type, "value": v}

    def _set_track_mute(self, track_index, mute, track_type):
        if track_type == "master":
            raise Exception("The master track cannot be muted")
        track = self._resolve_track(track_index, track_type)
        track.mute = bool(mute)
        return {"track_index": track_index, "track_type": track_type, "mute": bool(mute)}

    def _set_track_solo(self, track_index, solo, track_type):
        if track_type == "master":
            raise Exception("The master track cannot be soloed")
        track = self._resolve_track(track_index, track_type)
        track.solo = bool(solo)
        return {"track_index": track_index, "track_type": track_type, "solo": bool(solo)}

    def _set_track_arm(self, track_index, arm):
        """Arm is track-only. Guard via can_be_armed (reading .arm on a
        non-armable track raises RuntimeError, not AttributeError)."""
        track = self._resolve_track(track_index, "track")
        if not track.can_be_armed:
            raise Exception("This track cannot be armed (group/return/master)")
        track.arm = bool(arm)
        return {"track_index": track_index, "arm": bool(arm)}

    def _set_send(self, track_index, send_index, value, track_type):
        """Set a send amount to a raw 0..1 value (server pre-converts dB).
        Sends exist on regular and return tracks, not the master."""
        if track_type == "master":
            raise Exception("The master track has no sends")
        track = self._resolve_track(track_index, track_type)
        sends = track.mixer_device.sends
        if send_index < 0 or send_index >= len(sends):
            raise IndexError("Send index out of range")
        v = max(0.0, min(1.0, value))
        sends[send_index].value = v
        return {"track_index": track_index, "track_type": track_type,
                "send_index": send_index, "value": v}

    def _send_list(self, track):
        """Raw send values for a track, with destination return names. Returns
        [] for tracks that have no sends (e.g. master)."""
        out = []
        try:
            sends = track.mixer_device.sends
        except Exception:
            return out
        returns = self._song.return_tracks
        for i, send in enumerate(sends):
            name = returns[i].name if i < len(returns) else ("Send " + chr(65 + i))
            out.append({"index": i, "name": name, "value": send.value})
        return out

    def _get_sends(self, track_index, track_type):
        track = self._resolve_track(track_index, track_type)
        return {"track_index": track_index, "track_type": track_type,
                "sends": self._send_list(track)}

    def _get_return_tracks(self):
        out = []
        for i, track in enumerate(self._song.return_tracks):
            out.append({
                "index": i,
                "name": track.name,
                "mute": track.mute,
                "solo": track.solo,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "sends": self._send_list(track),
                "devices": [{"index": di, "name": d.name,
                             "class_name": d.class_name,
                             "type": self._get_device_type(d)}
                            for di, d in enumerate(track.devices)],
            })
        return {"return_tracks": out}

    def _get_master_track(self):
        track = self._song.master_track
        return {
            "name": track.name,
            "volume": track.mixer_device.volume.value,
            "panning": track.mixer_device.panning.value,
            "devices": [{"index": di, "name": d.name,
                         "class_name": d.class_name,
                         "type": self._get_device_type(d)}
                        for di, d in enumerate(track.devices)],
        }

    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise
    
    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri):
        """Load a browser item onto a track by its URI"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track

            # Report what the load added (server.py reads new_devices/devices_after).
            # Diff by name (multiset), not id(): Live reuses the device proxy when
            # replacing an instrument in place, so an identity diff misses swaps.
            before_names = [d.name for d in track.devices]

            # Load the item
            app.browser.load_item(item)

            # Synchronous for native devices; async VST/AU may not appear yet, so
            # new_devices can be empty on success -- devices_after is reliable.
            after_names = [d.name for d in track.devices]
            new_devices = list(after_names)
            for name in before_names:
                if name in new_devices:
                    new_devices.remove(name)

            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri,
                "new_devices": new_devices,
                "devices_after": after_names
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects
                ]
                
                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except Exception:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = self._get_browser_attrs(app)
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children.
            # Recurses up to max_depth levels; deeper subtrees are summarized with
            # has_more=True instead of being expanded. Bumping max_depth gives a
            # richer tree but is slower (browser children are materialized lazily).
            max_depth = 2

            def process_item(item, depth=0):
                if not item:
                    return None

                has_children = hasattr(item, 'children') and bool(item.children)
                node = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": has_children,
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": [],
                    "has_more": False
                }

                if has_children and depth < max_depth:
                    for child in item.children:
                        child_node = process_item(child, depth + 1)
                        if child_node:
                            node["children"].append(child_node)
                elif has_children:
                    node["has_more"] = True

                return node
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = self._get_browser_attrs(app)
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
