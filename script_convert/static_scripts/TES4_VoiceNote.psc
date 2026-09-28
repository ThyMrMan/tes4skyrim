ScriptName TES4_VoiceNote extends ObjectReference Hidden
{A FO3/FNV voice note carried as a book. Reading it plays the recording in the
player's head, spoken as the note's speaker, so the recording's own line and
its result script run as they did from the Pip-Boy.
See: docs/commentary/tes4_export_falloutnv.md#voice-notes-play-when-read}

Topic Property Recording Auto
Actor Property Speaker Auto

Event OnRead()
  Game.GetPlayer().Say(Recording, Speaker, true)
EndEvent
