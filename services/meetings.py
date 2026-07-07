"""
Meeting provider — uses Jitsi Meet (free, no account or API key required).
A unique room URL is generated per slot and stored on generated_slots.meeting_link.
"""
import hashlib


JITSI_BASE = "https://meet.jit.si"


def create_meeting(slot: dict, interviewer: dict, candidate: dict) -> dict:
    """
    Generate a unique, hard-to-guess Jitsi Meet room URL for a slot.
    Returns {"meeting_link": str, "external_event_id": str}.
    No API call required — the room is created automatically when the
    first participant visits the URL.
    """
    # Derive a short deterministic room name from slot ID + interviewer email
    raw = f"slot-{slot['id']}-{interviewer.get('email','')}"
    room_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    room_name  = f"MainstreetInterview-{room_hash}"

    meeting_link = f"{JITSI_BASE}/{room_name}"

    return {
        "meeting_link":      meeting_link,
        "external_event_id": room_name,
    }
