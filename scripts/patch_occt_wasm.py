#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reject nonfinite OCCT trim bounds using the existing OCCT exception path.

Bytecode patch for the exact pinned FreeCAD Web 1.0.8 distribution. The
corresponding source-level change is supplied in patches/occt/trim-finite.patch.
Do not apply to another module: the full input and target function hashes are
checked before writing. Normal finite inputs are unchanged.
"""
import hashlib
import struct
import sys
from pathlib import Path

MODULE = 'fafb7fb93d7c01a82967546c81c21b52ca3d60fa26a0dd10b0e404daf029a608'
BODY = '4527ce61009e9693905485ed063537d11674eb36e5e258e5fd745caa81223f52'
LOCAL_INDEX = 189632  # function 190294 minus 662 imported functions
LOCAL_PREFIX = bytes.fromhex('03027e037c0169')

def read_leb(b, pos):
    n=shift=0
    while True:
        c=b[pos]; pos+=1; n|=(c&127)<<shift
        if c<128: return n,pos
        shift+=7
        if shift>70: raise ValueError('invalid LEB')

def leb(n):
    out=bytearray()
    while True:
        c=n&127; n>>=7
        out.append(c | (128 if n else 0))
        if not n: return bytes(out)

def patch(path):
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=MODULE:
        raise ValueError('FreeCAD.wasm hash differs from the supported pinned engine')
    if data[:8]!=b'\x00asm\x01\x00\x00\x00':
        raise ValueError('invalid WASM header')
    # f64.ne catches NaN; abs(value)>DBL_MAX catches positive/negative infinity.
    # If either bound is nonfinite, set both to zero. SetTrim's first existing
    # check then throws Standard_ConstructionError, as it does for equal bounds.
    maxdouble=struct.pack('<d',sys.float_info.max)
    zero=bytes.fromhex('44')+struct.pack('<d',0.0)
    guard=(
        bytes.fromhex('2001200162 2002200262 72')
        + bytes.fromhex('20019944')+maxdouble+bytes.fromhex('64 72')
        + bytes.fromhex('20029944')+maxdouble+bytes.fromhex('64 72')
        + bytes.fromhex('0440')+zero+bytes.fromhex('2101')
        + zero+bytes.fromhex('2102 0b')
    )
    out=bytearray(data[:8]); pos=8; changed=0
    while pos<len(data):
        section_id=data[pos]; size,start=read_leb(data,pos+1); end=start+size
        if end>len(data): raise ValueError('section outside module')
        section=data[start:end]
        if section_id==10:
            count, at=read_leb(section,0)
            if LOCAL_INDEX>=count: raise ValueError('target function missing')
            for i in range(count):
                sizepos=at
                bodylen,at=read_leb(section,at)
                bodyend=at+bodylen
                if bodyend>len(section): raise ValueError('function outside code section')
                if i==LOCAL_INDEX:
                    body=section[at:bodyend]
                    if hashlib.sha256(body).hexdigest()!=BODY or not body.startswith(LOCAL_PREFIX):
                        raise ValueError('target function body differs')
                    newbody=LOCAL_PREFIX+guard+body[len(LOCAL_PREFIX):]
                    section=section[:sizepos]+leb(len(newbody))+newbody+section[bodyend:]
                    changed+=1
                    break
                at=bodyend
        out.append(section_id); out.extend(leb(len(section))); out.extend(section)
        pos=end
    if changed!=1: raise ValueError('code section target not found')
    path.write_bytes(out)
    print('OCCT_WASM_PATCHED',hashlib.sha256(out).hexdigest(),flush=True)

if __name__=='__main__':
    patch(Path(sys.argv[1]))
