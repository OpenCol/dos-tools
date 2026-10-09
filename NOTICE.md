# NOTICE

## What this repository is, and is not

These are tools for reading and writing the asset files of **Sid Meier's
Colonization** for DOS (1994), **© 1994 MicroProse Software, Inc.** The rights
in that game are held by its present owner, not by this project.

**This repository does not contain the game.** It ships no art, no text, no
sound and no executable from it. You bring your own copy; everything here
operates on files already on your disk. Even the one table the map preview
needs (which prime resource each terrain carries) is read out of your copy of
`VICEROY.EXE` at run time rather than copied into the source. Workspaces you
extract are gitignored for that reason.

The tools, their tests and their documentation are this project's own work and
are MIT licensed. The *formats* they implement were established by reverse
engineering carried out for interoperability and preservation, on a copy of the
game the author owns. The source cites the routines in `VICEROY.EXE` that
each claim rests on, by file offset.

## What comes out of these tools is still the game's

A workspace extracted with `coldos extract` holds the game's art and text in a
different file format. Converting it does not make it yours to redistribute. If
you publish a mod, publish the *changes* -- not the extracted originals.
