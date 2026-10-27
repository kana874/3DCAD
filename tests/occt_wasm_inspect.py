#!/usr/bin/env python3
import hashlib, sys
from pathlib import Path

def leb(b, p):
    n = shift = 0
    while True:
        c = b[p]; p += 1
        n |= (c & 127) << shift
        if c < 128: return n, p
        shift += 7
        if shift > 70: raise ValueError('invalid leb')

def string(b,p):
    n,p = leb(b,p)
    return bytes(b[p:p+n]).decode('utf8','replace'),p+n

def limits(b,p):
    flags,p=leb(b,p)
    _,p=leb(b,p)
    if flags & 1: _,p=leb(b,p)
    return p

b=Path(sys.argv[1]).read_bytes()
print('MODULE_SHA256',hashlib.sha256(b).hexdigest(),'SIZE',len(b),flush=True)
assert b[:8]==b'\x00asm\x01\x00\x00\x00'
p=8; sections={}
while p<len(b):
    sec=b[p]; n,p=leb(b,p+1); end=p+n
    assert end<=len(b)
    sections.setdefault(sec,[]).append(b[p:end])
    p=end
imports=sections[2][0]; count,p=leb(imports,0); imported=0
for _ in range(count):
    _,p=string(imports,p); _,p=string(imports,p); kind=imports[p];p+=1
    if kind==0:
        _,p=leb(imports,p); imported+=1
    elif kind==1:
        p+=1; p=limits(imports,p)
    elif kind==2: p=limits(imports,p)
    elif kind==3: p+=2
    elif kind==4:
        _,p=leb(imports,p); _,p=leb(imports,p)
    else: raise ValueError(('import type',kind))
func=sections[3][0]; size,p=leb(func,0); types=[]
for _ in range(size):
    v,p=leb(func,p);types.append(v)
target=190294
local=target-imported
assert 0<=local<len(types),(target,imported,len(types))
print('FUNCTION',target,'IMPORTED',imported,'LOCAL',local,'TYPE',types[local],flush=True)
code=sections[10][0];size,p=leb(code,0)
assert size==len(types)
for index in range(size):
    length,p=leb(code,p)
    if index==local:
        body=code[p:p+length]
        print('BODY_SHA256',hashlib.sha256(body).hexdigest(),'LENGTH',length,'PREFIX',body[:80].hex(),flush=True)
    p+=length
typ=sections[1][0]; size,p=leb(typ,0)
for i in range(size):
    kind=typ[p];p+=1
    if kind!=0x60: raise ValueError(('type kind',i,kind))
    n,p=leb(typ,p); params=list(typ[p:p+n]);p+=n
    n,p=leb(typ,p); result=list(typ[p:p+n]);p+=n
    if i==types[local]: print('TYPE_SIGNATURE',params,result,flush=True)
for custom in sections.get(0,[]):
    name,p=string(custom,0)
    if name!='name': continue
    while p<len(custom):
        sub=custom[p];n,p=leb(custom,p+1);end=p+n
        if sub==1:
            count,q=leb(custom,p)
            for _ in range(count):
                idx,q=leb(custom,q); name,q=string(custom,q)
                if idx==target: print('FUNCTION_NAME',name,flush=True)
        p=end
