
# INDI Mount Slew Process (Astrolabe Reference)

## Purpose

This document defines the correct property sequence required to slew an INDI-controlled telescope mount (including the INDI Telescope Simulator).

INDI mount motion is property-driven. A slew is not a single command — it is a stateful interaction using standard telescope properties.

This version reflects real observed driver behaviour:

- Writing coordinates triggers motion.
- `ON_COORD_SET` acts as a latched mode flag.
- Coordinate updates must be atomic.

---

# Core Behaviour Model

## 1. ON_COORD_SET is a Mode Flag

`ON_COORD_SET` determines what the driver does when coordinates are written:

- SLEW → move to target and stop
- TRACK → move and begin tracking
- SYNC → sync current position

⚠️ Setting `ON_COORD_SET` does NOT move the mount.

It simply sets the behaviour for future coordinate writes.

This flag remains latched until changed.

---

## 2. Writing Coordinates Triggers Motion

Motion occurs when:

EQUATORIAL_EOD_COORD.RA;DEC = <value>;<value>

is written atomically.

Once `ON_COORD_SET.SLEW` (or TRACK) has been set once, any subsequent atomic coordinate write triggers movement immediately.

---

# Correct Slew Procedure

## 1. Ensure Connection

CONNECTION.CONNECT = On

Wait until state = OK.

---

## 2. Ensure Mount is Unparked (if property exists)

TELESCOPE_PARK.UNPARK = On

Mount will not slew while parked.

---

## 3. (Recommended) Set Time and Location

GEOGRAPHIC_COORD (lat, lon, elevation)
TIME_UTC (UTC timestamp)

Required for real mounts. Simulator may not enforce this.

---

## 4. Set Slew Mode (Once)

ON_COORD_SET.SLEW = On

This only needs to be done once per session unless mode changes.

---

## 5. Trigger Slew via Atomic Coordinate Write

IMPORTANT: RA and DEC must be written atomically:

EQUATORIAL_EOD_COORD.RA;DEC = <RA_hours>;<DEC_degrees>

Example:

EQUATORIAL_EOD_COORD.RA;DEC = 5.591;-5.45

⚠️ RA is in HOURS, not degrees.
⚠️ When using `indi_setprop`, prefer explicit type flags:
- `-s` for switch vectors (e.g., `ON_COORD_SET`)
- `-n` for number vectors (e.g., `EQUATORIAL_EOD_COORD`)

Do NOT send RA and DEC in separate commands.

---

# Monitoring Slew Progress

During motion:

EQUATORIAL_EOD_COORD._STATE = Busy

When complete:

EQUATORIAL_EOD_COORD._STATE = OK

Recommended monitoring:

- Subscribe to property updates
- Or poll _STATE
- Implement timeout handling
- Optionally verify final RA/DEC matches target

---

# Minimal State Machine for Astrolabe

On connect:

    connect()
    unpark_if_needed()
    set ON_COORD_SET = SLEW

On each goto:

    write EQUATORIAL_EOD_COORD.RA;DEC atomically
    wait until _STATE == OK or timeout

---

# Important Implementation Rules

1. Treat ON_COORD_SET as persistent driver state.
2. Always write RA and DEC atomically.
3. Do not assume property writes are synchronous.
4. Monitor property state for completion.
5. Log property snapshots on failure.
6. Handle parked and disconnected states explicitly.

---

# Common Failure Modes

1. Mount is parked.
2. RA provided in degrees instead of hours.
3. RA and DEC written separately.
4. Wrong coordinate property (TARGET_EOD_COORD vs EQUATORIAL_EOD_COORD).
5. Not monitoring correct device name.
6. Talking to wrong INDI server/port.

---

# Testing With Telescope Simulator

Start:

    indiserver indi_simulator_telescope

Then:

1. Connect
2. Unpark
3. Set ON_COORD_SET.SLEW
4. Write EQUATORIAL_EOD_COORD.RA;DEC
5. Confirm RA/DEC values update and _STATE transitions

---

End of document.
