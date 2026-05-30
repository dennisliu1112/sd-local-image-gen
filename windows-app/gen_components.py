"""
gen_components.py - Generate WiX v4 components from a dist directory.
Usage: python gen_components.py <dist_dir> <output.wxs>
"""
import sys, uuid, os
from pathlib import Path
from xml.sax.saxutils import escape

dist_dir = Path(sys.argv[1])
out_path  = Path(sys.argv[2])

def make_id(p: Path) -> str:
    return "F_" + p.as_posix().replace("/","_").replace(".","_").replace("-","_")

lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">',
    '  <Fragment>',
    '    <ComponentGroup Id="DistComponents" Directory="INSTALLFOLDER">',
]

for f in sorted(dist_dir.rglob("*")):
    if not f.is_file():
        continue
    rel   = f.relative_to(dist_dir)
    fid   = make_id(rel)
    cid   = "C" + fid[1:]
    guid  = str(uuid.uuid5(uuid.NAMESPACE_URL, str(rel))).upper()
    src   = escape(str(f))

    # subdirectory handling: use Subdirectory attribute
    sub = str(rel.parent).replace("/","\\") if rel.parent != Path(".") else ""
    sub_attr = f' Subdirectory="{sub}"' if sub else ""

    lines += [
        f'      <Component Id="{cid}" Guid="{guid}"{sub_attr}>',
        f'        <File Id="{fid}" Source="{src}" KeyPath="yes" />',
        f'      </Component>',
    ]

lines += [
    '    </ComponentGroup>',
    '  </Fragment>',
    '</Wix>',
]

out_path.write_text("\n".join(lines), encoding="utf-8")
print(f"Generated {out_path} with {sum(1 for l in lines if '<File ' in l)} files.")
