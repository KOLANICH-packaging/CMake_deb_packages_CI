#!/usr/bin/env python3
import sys
from io import StringIO, BytesIO
from pathlib import Path, PurePath
import struct
import re
import os
from itertools import chain
import warnings
import tarfile
import csv

import sh
import gpg
from tqdm.autonotebook import tqdm
from hashlib import sha256

import requests
from pydebhelper import *
from getLatestVersionAndURLWithGitHubAPI import getTargets

CMakePreambleMessage = "CMake is used to control the software compilation process using simple platform and compiler independent configuration files. CMake generates native makefiles and workspaces that can be used in the compiler environment of your choice.\n\n"

ourCMakePrefix = "vanilla-cmake"

cmakeCommonDeps= ("libarchive13", "libc6", "libcurl4", "libgcc1", "libjsoncpp1", "zlib1g", "librhash0", "libstdc++6", "libuv1")

#the descriptions are taken from the official Debian packages (http://deb.debian.org/debian/pool/main/c/cmake/cmake_3.13.4-1.debian.tar.xz), their licenses are there
config = OrderedDict()
config[ourCMakePrefix] = {
	"descriptionShort": "cross-platform, open-source make system",
	"descriptionLong": (
"""CMake is used to control the software compilation process using simple platform and compiler independent configuration files. CMake generates native makefiles and workspaces that can be used in the compiler environment of your choice. CMake is quite sophisticated: it is possible to support complex environments requiring system configuration, pre-processor generation, code generation, and template instantiation.

CMake was developed by Kitware as part of the NLM Insight Segmentation and Registration Toolkit project. The ASCI VIEWS project also provided support in the context of their parallel computation environment. Other sponsors include the Insight, VTK, and VXL open source software communities."""
	),
	"rip": {
		"bin": ["cmake", "cpack", "ctest"],
		"man": [("cmake", 1), ("cpack", 1), ("ctest", 1), (None, 7)],
	},

	"depends": (*cmakeCommonDeps, ourCMakePrefix+"-data", "libexpat1", "procps"),
	"provides": ("cmake",),
	"recommends": ("gcc", "make"),
	"suggests": ("cmake-doc", "ninja-build"),
	"conflicts": ("cmake", ),
	"replaces": ("cmake", ),
}
config[ourCMakePrefix+"-curses"] = {
	"descriptionShort": "curses based user interface for CMake (ccmake)",
	"descriptionLong": CMakePreambleMessage + 'This package provides the CMake curses interface. Project configuration settings may be specified interactively through this GUI. Brief instructions are provided at the bottom of the terminal when the program is running. The main executable file for this GUI is "ccmake".',
	"rip": {
		"bin": ["ccmake"],
		"man": [("ccmake", 1)],
	},
	"depends": (ourCMakePrefix, *cmakeCommonDeps, "libncurses6", "librhash0", "libstdc++6", "libtinfo6", ),
	"provides": ("cmake-curses-gui", "cmake-curses"),
	"conflicts": ("cmake-curses", ),
	"replaces": ("cmake-curses", ),
}
config[ourCMakePrefix+"-qt-gui"] = {
	"descriptionShort": "Qt based user interface for CMake (cmake-gui)",
	"descriptionLong": CMakePreambleMessage + 'This package provides the CMake Qt based GUI. Project configuration settings may be specified interactively. Brief instructions are provided at the bottom of the window when the program is running. The main executable file for this GUI is "cmake-gui".',
	"rip": {
		"bin": ["cmake-gui"],
		"man": [("cmake-gui", 1)],
		"other": ["share/applications", "share/icons", "share/mime"]
	},
	"depends": (ourCMakePrefix, *cmakeCommonDeps, "libqt5core5a", "libqt5gui5", "libqt5widgets5", ),
	"provides": ("cmake-gui", "cmake-qt-gui"),
	"conflicts": ("cmake-qt-gui", ),
	"replaces": ("cmake-qt-gui", ),
}
config[ourCMakePrefix+"-data"] = {
	"arch": "all",
	"descriptionShort": "CMake data files (modules, templates and documentation)",
	"descriptionLong": CMakePreambleMessage + "This package provides CMake architecture independent data files (modules, templates, documentation etc.). Unless you have cmake installed, you probably do not need this package.",
	"rip": {
		"other": ["share/aclocal"] # the dir is determined automatically (and inserted here)!
	},
	"provides": ("cmake-data",),
	"conflicts": ("cmake-data", ),
	"replaces": ("cmake-data", ),
}


def ripCMakePackage(unpackedDir, packagesDir, version, maintainer, builtDir, licenseFilePath):
	results = {}

	for pkgName, pkgCfg in config.items():
		pkgCfg = type(pkgCfg)(pkgCfg)
		rip = pkgCfg["rip"]
		del pkgCfg["rip"]

		with Package(pkgName, packagesDir, version=version, section="devel", maintainer=maintainer, builtDir=builtDir, homepage="https://cmake.org/download/", **pkgCfg) as pkg:
			if "other" in rip:
				for el in rip["other"]:
					pkg.rip(unpackedDir / el, "usr/" + el)

			if "bin" in rip:
				for el in rip["bin"]:
					a = "bin/" + el
					aUnp = unpackedDir / a
					pkg.rip(aUnp, "usr/" + a)
			
			if "man" in rip:
				for name, section in rip["man"]:
					sectionDir = "man/man" + str(section)
					if name:
						a = sectionDir + "/" + name + "." + str(section)
						aUnp = unpackedDir / a
						pkg.rip(aUnp, "usr/share/" + a)
					else:
						for manF in (unpackedDir / sectionDir).iterdir():
							pkg.rip(manF, "usr/share/"+str(manF.relative_to(unpackedDir)))
			
			pkg.copy(licenseFilePath, "usr/share/doc/"+pkgName+"/copyright")
			results[pkgName] = pkg
	
	
	with Package(ourCMakePrefix+"-doc", packagesDir, version=version, section="devel", maintainer=maintainer, builtDir=builtDir, homepage="https://cmake.org/download/", **{
		"arch": "all",
		"descriptionShort": "extended documentation in various formats for CMake",
		"descriptionLong": CMakePreambleMessage + "This package provides additional documentation in various formats like HTML or plain text.",
		"provides": ("cmake-doc",),
		"conflicts": ("cmake-doc", ),
		"replaces": ("cmake-doc", ),
	}) as docPkg:
		pkg.rip(unpackedDir / "doc", "usr/share/doc")
		results[ourCMakePrefix+"-doc"] = docPkg

	return results



def isSubdir(parent: Path, child: Path) -> bool:
	parent = parent.absolute().resolve()
	child = child.absolute().resolve().relative_to(parent)
	for p in child.parts:
		if p == "..":
			return False
	return True


def unpack(archPath, extrDir):
	extrDir = extrDir.resolve()
	packedSize = archPath.stat().st_size
	with archPath.open("rb") as arch:
		arch.seek(packedSize - 4)
		unpackedSize = struct.unpack("<I", arch.read(4))[0]

	with tarfile.open(archPath, "r:gz") as arch:
		with tqdm(total=unpackedSize, unit="B", unit_divisor=1024, unit_scale=True) as pb:
			for f in arch:
				fp = (extrDir / f.name).absolute()
				if isSubdir(extrDir, fp):
					if fp.is_file() or fp.is_symlink():
						fp.unlink()
					fp.parent.mkdir(parents=True, exist_ok=True)
					arch.extract(f, extrDir, set_attrs=True)
					pb.set_postfix(file=str(fp.relative_to(extrDir)), refresh=False)
					pb.update(f.size)



class HashesFilesDialect(csv.Dialect):
	quoting=csv.QUOTE_NONE
	delimiter=" "
	lineterminator="\n"

def parseHashesFile(hashes:str):
	res={}
	with StringIO(hashes) as csvIO:
		for line in csv.reader(csvIO, dialect=HashesFilesDialect):
			res[line[2]]=line[0]

	return res


currentProcFileDescriptors = Path("/proc") / str(os.getpid()) / "fd"

fj = sh.firejail.bake(noblacklist=str(currentProcFileDescriptors), _fg=True)

aria2c = fj.aria2c.bake(_fg=True, **{"continue": "true", "check-certificate": "true", "enable-mmap": "true", "optimize-concurrent-downloads": "true", "j": 16, "x": 16, "file-allocation": "falloc"})
aria2c = sh.Command("/usr/bin/aria2c").bake(_fg=True, **{"continue": "true", "check-certificate": "true", "enable-mmap": "true", "optimize-concurrent-downloads": "true", "j": 16, "x": 16, "file-allocation": "falloc"})

def download(targets):
	args = []

	for dst, uri in targets.items():
		args += [uri, linesep, " ", "out=", str(dst), linesep]

	pO, pI = os.pipe()
	with os.fdopen(pI, "w") as pIF:
		pIF.write("".join(args))
		pIF.flush()
	try:
		aria2c(**{"input-file": str(currentProcFileDescriptors / str(pO))})
	finally:
		os.close(pO)
		try:
			os.close(pI)
		except:
			pass

versionRxText = "(?:\\d+\\.){1,2}\\d+(?:-rc\\d+)?"
vmTagRx = re.compile("^v("+versionRxText+")$")
platformMarker = "Linux-x86_64"
hashFuncName = "SHA-256"
downloadFileNameRx = re.compile("^" + "-".join(("cmake", versionRxText, platformMarker)) + "\\.tar\\.gz$")
hashesFileNameRxText="-".join(("cmake", versionRxText,  hashFuncName)) + "\\.txt"
hashesSigFileNameRxText=hashesFileNameRxText+"\\.(?:asc|sig|gpg)"
signingKeyFingerprint="CBA23971357C2E6590D9EFD3EC8FEF3A7BFB4EDA"
candidateDirRx = re.compile("^cmake-"+versionRxText+"$")
licenseFileURI = "https://gitlab.kitware.com/cmake/cmake/raw/master/Copyright.txt"


gpgContext = gpg.Context(armor=True, offline=True)

def findKeyByFingerprint(fp):
	for k in gpgContext.op_keylist_all():
		if k.fpr == fp:
			return k

def verifyBlob(signedData: bytes, signature: bytes, *, keyFingerprint:str=None, subkeyFingerprint:str=None):
	allowedFingerprints=set()
	if keyFingerprint:
		key=findKeyByFingerprint(keyFingerprint.upper())
		for sk in key.subkeys:
			allowedFingerprints.add(sk.fpr)
	elif subkeyFingerprint:
		allowedFingerprints.add(subkeyFingerprint.upper())
	
	data, res = gpgContext.verify(signedData, signature)
	#print(res)
	for s in res.signatures:
		#print(s)
		if s.fpr in allowedFingerprints:
			return True
	raise Exception("Wrong public keys used: "+ " ".join((s.fpr for s in res.signatures)))

def findCMakeDataDir(cmakeUnpackedRoot):
	cmakeDataDir=None
	for cand in (cmakeUnpackedRoot / "share").iterdir():
		#print(cand, cand.is_dir(), candidateDirRx.match(cand.name))
		if cand.is_dir():
			if candidateDirRx.match(cand.name):
				cmakeDataDir = cand
				break
	return cmakeDataDir

def doBuild():
	thisDir = Path(".")

	downloadDir = Path(thisDir / "downloads")
	archPath = Path(downloadDir/"x86_64.tar.gz")
	unpackDir = thisDir / "CMake_unpacked"
	packagesRootsDir = thisDir / "packagesRoots"
	builtDir = thisDir / "packages"
	repoDir = thisDir / "public" / "repo"
	licenseFilePath = thisDir / "licenses" / "CMake-BSD.txt"

	tgts=list(getTargets("Kitware/CMake", None, vmTagRx, {
		"binary":downloadFileNameRx,
		"hashes": re.compile("^" + hashesFileNameRxText + "$"),
		"hashesSig": re.compile("^" + hashesSigFileNameRxText + "$"), 
	}))
	
	selectedTarget = max(tgts)


	print("Selected release:", selectedTarget, file=sys.stderr)
	

	hashesRaw=requests.get(selectedTarget.files["hashes"].uri).content
	hashesSigRaw=requests.get(selectedTarget.files["hashesSig"].uri).content

	verifyBlob(hashesRaw, hashesSigRaw, keyFingerprint=signingKeyFingerprint)
	
	hashes = parseHashesFile(hashesRaw.decode("utf-8"))
	archiveFileName = PurePath(selectedTarget.files["binary"].uri).name
	archiveEtalonHash = hashes[archiveFileName].lower()

	downloadTargets = {
		archPath: selectedTarget.files["binary"].uri,
		licenseFilePath: licenseFileURI
	}

	download(downloadTargets)
	actualFileHash=sumFile(archPath, (sha256,))["sha256"]
	if actualFileHash.lower() != archiveEtalonHash:
		raise Exception("Bad hash for the downloaded archive!")

	unpack(archPath, unpackDir)

	cmakeUnpackedRoot = unpackDir / ('cmake-'+selectedTarget.version+'-'+platformMarker)

	cmakeDataDir=findCMakeDataDir(cmakeUnpackedRoot)
	config[ourCMakePrefix+"-data"]["rip"]["other"].append(str(cmakeDataDir.relative_to(cmakeUnpackedRoot)))

	builtDir.mkdir(parents=True, exist_ok=True)

	maintainer = Maintainer()
	pkgs = ripCMakePackage(cmakeUnpackedRoot, packagesRootsDir, tgts[0].version, maintainer=maintainer, builtDir=builtDir, licenseFilePath=licenseFilePath)

	for pkg in pkgs.values():
		pkg.build()
	
	with Repo(root=repoDir, descr=maintainer.name+"'s repo for apt with CMake binary packages, built from the official builds on GitHub") as r:
		for pkg in pkgs.values():
			r += pkg
		print(r.packages2add)
	



if __name__ == "__main__":
	doBuild()
