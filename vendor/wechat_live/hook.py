"""Live-session LLDB reader. No launch, quit, resign or process kill commands.

Based on wxvault v0.1.0 hook.py (Apache-2.0; see vendor/licenses/wxvault).
Modified for an already-running Apple Silicon WeChat: capture AES operations,
limit reads, report stages, support cancellation, and always detach in finally.
See also jackwener/wx-cli-again macOS scanner for the live-attach approach.
"""
import json
import os
import re
import time
from pathlib import Path
import lldb


def private_json(path, value):
    temporary = str(path) + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
    owner = Path(path).parent.stat()
    os.chown(temporary, owner.st_uid, owner.st_gid)
    os.replace(temporary, path)


def memory(process, address, count):
    error = lldb.SBError()
    value = process.ReadMemory(address, count, error)
    return bytes(value) if error.Success() and value else b''


def read_session(debugger):
    job = Path(os.environ['CHATARCHIVE_LIVE_JOB'])
    salts = json.loads((job / 'salts.json').read_text())
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()
    if not process or not process.IsValid():
        private_json(job / 'reader.json', {'phase': 'failed', 'code': 'attach_failed'})
        return
    debugger.SetAsync(True)
    breakpoints = []
    pairs = set()
    keys = set()
    def add_key(key):
        if len(key) == 32 and len(keys) < 128:
            keys.add(key.hex())
    def save():
        for key in keys:
            for salt in salts:
                pairs.add((key, bytes(b ^ 0x3a for b in bytes.fromhex(salt)).hex()))
        private_json(job / 'pairs.json', [{'key': k, 'salt': s} for k, s in pairs])
    try:
        # A short, bounded scan of writable memory supports older WCDB caches.
        regions = process.GetMemoryRegions()
        deadline = time.monotonic() + 3
        scanned = 0
        for index in range(regions.GetSize()):
            if time.monotonic() >= deadline or scanned >= 64 * 1024**2 or (job / 'cancel').exists():
                break
            region = lldb.SBMemoryRegionInfo()
            if not regions.GetMemoryRegionAtIndex(index, region) or not region.IsReadable() or not region.IsWritable():
                continue
            cursor = region.GetRegionBase()
            end = region.GetRegionEnd()
            overlap = b''
            while cursor < end and time.monotonic() < deadline and scanned < 64 * 1024**2:
                length = min(1024 * 1024, end - cursor)
                block = memory(process, cursor, length)
                combined = overlap + block
                for match in re.finditer(rb"x'([0-9a-fA-F]{64})([0-9a-fA-F]{32})'", combined):
                    if match[2].decode().lower() in salts:
                        add_key(bytes.fromhex(match[1].decode()))
                overlap = combined[-100:]
                cursor += length
                scanned += length
        specs = [('CCKeyDerivationPBKDF', 'pbkdf'), ('CCCryptorCreate', 'aes'),
                 ('CCCryptorCreateWithMode', 'aes_mode')]
        types = {}
        for symbol, kind in specs:
            bp = target.BreakpointCreateByName(symbol)
            breakpoints.append(bp.GetID())
            types[bp.GetID()] = kind
        listener = lldb.SBListener('chatarchive-live-reader')
        process.GetBroadcaster().AddListener(listener, lldb.SBProcess.eBroadcastBitStateChanged)
        private_json(job / 'reader.json', {'phase': 'reading', 'code': 'open_chat'})
        process.Continue()
        deadline = time.monotonic() + 60
        event = lldb.SBEvent()
        while time.monotonic() < deadline and len(keys) < 128:
            if (job / 'cancel').exists():
                break
            if not listener.WaitForEvent(1, event):
                continue
            state = lldb.SBProcess.GetStateFromEvent(event)
            if state in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
                break
            if state != lldb.eStateStopped:
                continue
            hit = False
            for thread in process:
                if thread.GetStopReason() != lldb.eStopReasonBreakpoint:
                    continue
                kind = types.get(thread.GetStopReasonDataAtIndex(0))
                if kind is None:
                    continue
                hit = True
                frame = thread.GetFrameAtIndex(0)
                registers = [frame.FindRegister('x%d' % i).GetValueAsUnsigned() for i in range(9)]
                if kind == 'pbkdf' and registers[0] == 2 and registers[2] == 32 and registers[4] == 16 and registers[6] == 2:
                    key = memory(process, registers[1], 32)
                    salt = memory(process, registers[3], 16)
                    if len(key) == 32 and len(salt) == 16 and bytes(b ^ 0x3a for b in salt).hex() in salts and len(pairs) < 65536:
                        pairs.add((key.hex(), salt.hex()))
                elif kind == 'aes' and registers[1] == 0 and registers[4] == 32:
                    add_key(memory(process, registers[3], 32))
                elif kind == 'aes_mode' and registers[2] == 0 and registers[5] == 32:
                    add_key(memory(process, registers[4], 32))
            if not hit:
                break  # Do not resume an unrelated exception or user breakpoint.
            save()
            process.Continue()
        save()
        private_json(job / 'reader.json', {'phase': 'finished', 'code': 'cancelled' if (job / 'cancel').exists() else 'read_finished'})
    except Exception:
        private_json(job / 'reader.json', {'phase': 'failed', 'code': 'reader_failed'})
    finally:
        if process.GetState() not in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
            try:
                process.Stop()
            finally:
                for identifier in breakpoints:
                    target.BreakpointDelete(identifier)


def __lldb_init_module(debugger, internal_dict):
    # Even setup errors must detach an already attached process. No Kill or
    # launch API is used; deleting our breakpoints precedes detachment.
    process = debugger.GetSelectedTarget().GetProcess()
    try:
        read_session(debugger)
    finally:
        if process and process.IsValid() and process.GetState() not in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
            process.Detach()
