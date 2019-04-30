from collections import defaultdict, OrderedDict
from pathlib import Path
from hashlib import md5, sha256, blake2b, sha3_512
from os import readlink, linesep, fchdir
import os
import mmap
import warnings
import sh
from itertools import chain
import typing
import shutil

dpkgDebBuild = sh.Command("fakeroot").bake("dpkg-deb", "-Sextreme", b=True, _fg=True)
dpkgSig = sh.Command("dpkg-sig").bake(s="builder", _fg=True)


def createConfigFromDict(d):
	return linesep.join(str(k) + ": " + str(v) for k, v in d.items()) + linesep


class Maintainer:
	__slots__ = ("name", "email")

	def __init__(self, name: str = None, email: str = None):
		if not name:
			name = os.environ.get("DEBFULLNAME", "Anonymous")

		if not email:
			email = os.environ.get("DEBEMAIL", None)

		self.name = name
		self.email = email

	def __str__(self):
		res = self.name
		if res and self.email:
			res += " <" + self.email + ">"
		return res

	def __repr__(self):
		return str(self)


def sumFile(path, hashers=(md5,)):
	"""Creates an object with hashsums of a file"""
	HObjs = [h() for h in hashers]
	if path.stat().st_size:
		with path.open("rb") as f:
			n = f.fileno()
			with mmap.mmap(f.fileno(), 0, prot=mmap.PROT_READ) as m:
				for h in HObjs:
					h.update(m)
	return {h.name: h.hexdigest() for h in HObjs}


class Package:
	__slots__ = ("root", "hashsums", "controlDict", "_debPath", "builtDir")
	hashfuncs = (md5, sha256, blake2b, sha3_512)

	def __init__(self, packageName, parentDir, arch="amd64", builtDir=None, **kwargs):
		self.root = None
		self.hashsums = None
		self.root = parentDir / packageName
		self.controlDict = dict(kwargs)
		self.controlDict["name"] = packageName
		self.controlDict["arch"] = arch
		self._debPath = None
		self.builtDir = builtDir

	def __enter__(self):
		self.hashsums = defaultdict(OrderedDict)
		return self

	def __exit__(self, *args, **kwargs):
		self.createControl()
		self.createSums()

	@property
	def name(self):
		return self.controlDict["name"]

	@name.setter
	def name(self, val: str):
		self.controlDict["name"] = val

	@property
	def arch(self):
		return self.controlDict["arch"]

	@arch.setter
	def arch(self, val: str):
		self.controlDict["arch"] = val

	@property
	def version(self):
		return self.controlDict["version"]

	@version.setter
	def version(self, val: str):
		self.controlDict["version"] = val

	@property
	def debian(self):
		debDir = self.root / "DEBIAN"
		debDir.mkdir(parents=True, exist_ok=True)
		return debDir

	def createControl(self):
		ctrlF = self.debian / "control"
		print(self.controlDict)
		ctrlF.write_text(createControlText(**self.controlDict))

	def createSums(self):
		for hashName, hashes in self.hashsums.items():
			hashes = type(hashes)(sorted(hashes.items(), key=lambda x: x[0]))
			if hashes:
				sumsF = self.debian / (hashName + "sums")
				with sumsF.open("wt") as f:
					f.writelines(v + "  " + k + linesep for k, v in hashes.items())

	def resolvePath(self, p: Path, recurseSymlinks=True) -> Path:
		while p.is_symlink():
			p = self.root / readlink(p)

		return p.resolve()
	
	def checksumPath(self, resPath):
		files = []
		if resPath.is_dir():
			files = [f for f in resPath.glob("**/*") if (f.is_file() and not f.is_symlink())]
		else:
			if not resPath.is_symlink():
				files = [resPath]

		#print(files)

		for f in files:
			hashes = sumFile(f, self.hashfuncs)
			for hashFuncName, h in hashes.items():
				self.hashsums[hashFuncName][str(f.relative_to(self.root))] = h

	def copy(self, src, dst):
		"""src is path, dst is an abstract path within root"""
		resPath = self.root / dst

		if src.is_dir():
			resPath.mkdir(parents=True, exist_ok=True)
			for f in src.iterdir():
				self.copy(f, resPath / f.name)
		else:
			resPath.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(str(src), str(resPath))
		

		self.checksumPath(resPath)


	def rip(self, src, dst):
		"""src is path, dst is an abstract path within root"""
		resPath = self.root / dst

		if (resPath.exists() or resPath.is_symlink()) and not (src.exists() or src.is_symlink()):
			warnings.warn(str(resPath) + " already exists")
		elif (resPath.exists() and resPath.is_dir()):
			self.copy(src, resPath)
		else:
			#print("src", src, "res", resPath, resPath.exists(), src.is_dir(), src.is_symlink())

			if src.is_dir():
				resPath.mkdir(parents=True, exist_ok=True)
			else:
				resPath.parent.mkdir(parents=True, exist_ok=True)

			src.rename(resPath)

			self.checksumPath(resPath)

	@property
	def debPath(self):
		if not self._debPath and self.builtDir:
			self.build(self.builtDir)
		return self._debPath

	def build(self, debPath=None):
		if self.builtDir and not debPath:
			debPath = self.builtDir

		if debPath.is_dir():
			debPath = debPath / (self.name + "_" + self.version + "_" + self.arch + ".deb")

		dpkgDebBuild(self.root, str(debPath))
		dpkgSig(str(debPath))
		self._debPath = debPath.resolve()
		return debPath


class DebianRelease:
	__slots__ = ("codenames", "version")

	origin = "Debian"
	def __init__(self, codenames=("stretch", "stable"), version=(9, 0)):
		self.codenames = codenames
		self.version = version

	@property
	def suite(self):
		return self.codenames[-1]
	
	@property
	def codename(self):
		return self.codenames[0]


class UbuntuRelease(DebianRelease):
	origin = "Ubuntu"


knownReleases = OrderedDict((
	("Ubuntu", (
		UbuntuRelease(("disco",), (19, 4)),
		UbuntuRelease(("cosmic",), (18, 10)),
		UbuntuRelease(("bionic",), (18, 4)),
		UbuntuRelease(("artful",), (17, 10)),
		UbuntuRelease(("zesty",), (17, 4)),
		UbuntuRelease(("yakkety",), (16, 10)),
		UbuntuRelease(("xenial",), (16, 4))
	)),
	("Debian", (
		DebianRelease(("sid", "unstable"), (10, 0)),
		DebianRelease(("buster", "testing"), (10, 0)),
		DebianRelease(("stretch", "stable"), (9, 0)),
		DebianRelease(("jessie", "oldstable"), (8, 0)),
		DebianRelease(("wheezy", "oldoldstable"), (7, 0))
	))
))

def createDistributionText(descr, release, components=("contrib", "non-free"), archs=("amd64",), signatureKey="default", compressions=("xz",)):
	d = OrderedDict()
	d["Description"] = descr
	d["Origin"] = release.origin
	d["Suite"] = release.suite
	d["Codename"] = release.codenames[0]
	d["Version"] = release.version

	d["Architectures"] = " ".join(set(archs) - {"all"})
	d["Components"] = " ".join(components)
	d["UDebComponents"] = d["Components"]

	compressions = " ".join("." + c for c in compressions)

	d["DebIndices"] = "Packages Release " + compressions
	d["DscIndices"] = "Sources Release " + compressions
	d["Contents"] = compressions
	d["SignWith"] = signatureKey
	return createConfigFromDict(d)

def createDistributionsText(descr, releases, components=("contrib", "non-free"), archs=("amd64",), signatureKey="default", compressions=("xz",)):
	return (linesep*2).join(createDistributionText(descr, release=r, components=components, archs=archs, signatureKey=signatureKey, compressions=compressions) for r in releases)


repreproCmd = sh.reprepro.bake(_fg=True)
includeDebCmd = repreproCmd.includedeb
exportCmd = repreproCmd.export
createSymlinksCmd = repreproCmd.createsymlinks


class Repo:
	__slots__ = ("root", "distrsDict", "packages2add")

	def __init__(self, root, descr, releases=3, **kwargs):
		self.root = root
		self.distrsDict = dict(**kwargs)
		self.distrsDict["descr"] = descr
		
		releases_ = []
		if releases is None:
			for distroReleases in knownReleases.values():
				releases_ += distroReleases
		elif isinstance(releases, int):
			for distroReleases in knownReleases.values():
				releases_ += distroReleases[:releases]
		else:
			releases_ = releases
		releases = releases_

		self.distrsDict["releases"] = releases
		print(releases, self.releases)

		self.packages2add = None

	@property
	def archs(self):
		return self.distrsDict["archs"]

	@archs.setter
	def archs(self, v):
		self.distrsDict["archs"] = v

	@property
	def releases(self):
		print("releases", self.distrsDict["releases"])
		return self.distrsDict["releases"]

	@releases.setter
	def releases(self, v):
		print("releases <-", v)
		self.distrsDict["releases"] = v

	@property
	def mainRelease(self):
		print(self.releases)
		return self.releases[-1]

	@property
	def suite(self):
		return self.mainRelease.suite
	
	@property
	def codename(self):
		return self.mainRelease.codename

	@property
	def conf(self):
		rootDir = self.root / "conf"
		rootDir.mkdir(parents=True, exist_ok=True)
		return rootDir

	def createDistributions(self):
		ctrlF = self.conf / "distributions"
		ctrlF.write_text(createDistributionsText(**self.distrsDict))

	def __enter__(self):
		self.packages2add = []
		if "archs" not in self.distrsDict:
			self.distrsDict["archs"] = set()
		else:
			self.distrsDict["archs"] = set(self.distrsDict["archs"])

		return self

	def __iadd__(self, pkg: typing.Union[Package, Path]):
		self.packages2add.append(pkg)
		if isinstance(pkg, Package):
			self.archs |= {pkg.arch}
		return self

	def generateRepo(self):
		oldPath = Path.cwd()
		oldDescr = os.open(oldPath, os.O_RDONLY)
		rootDescr = None
		# try:
		rootDescr = os.open(self.root, os.O_RDONLY)
		fchdir(rootDescr)
		exportCmd()
		createSymlinksCmd()
		for pkg in self.packages2add:
			if isinstance(pkg, Path):
				pkgPath = pkg
			else:
				pkgPath = pkg.debPath
			print("adding", pkgPath)
			for r in self.releases:
				for cn in r.codenames:
					includeDebCmd(cn, pkgPath)

		self.packages2add = []
		# finally:
		if rootDescr is not None:
			os.close(rootDescr)
		fchdir(oldDescr)
		os.close(oldDescr)

	def __exit__(self, *args, **kwargs):
		self.createDistributions()
		self.generateRepo()


def createControlText(name, version=(0, 0, 0), homepage=None, depends=None, provides=None, section="misc", arch="amd64", priority="optional", maintainer=None, size=None, descriptionShort="", descriptionLong="", additionalProps=None, recommends=None, suggests=None, replaces=None, conflicts=None):
	d = OrderedDict()
	d["Package"] = name
	d["Version"] = ".".join(str(el) for el in version) if isinstance(version, tuple) else str(version)
	d["Architecture"] = arch
	if maintainer:
		d["Maintainer"] = str(maintainer)
	if size:
		d["Installed-Size"] = size
	d["Section"] = section
	d["Priority"] = priority
	if homepage:
		d["Homepage"] = homepage
	if depends:
		d["Depends"] = ", ".join(depends)

	if provides:
		d["Provides"] = ", ".join(provides)
	
	if recommends:
		d["Recommends"] = ", ".join(recommends)
	
	if suggests:
		d["Suggests"] = ", ".join(suggests)
	
	if replaces:
		d["Replaces"] = ", ".join(replaces)
	
	if conflicts:
		d["Conflicts"] = ", ".join(conflicts)

	d["Description"] = descriptionShort

	if descriptionLong:
		d["Description"] += linesep + "".join("\t" + l for l in descriptionLong.splitlines())

	if additionalProps:
		d.update(additionalProps)

	return createConfigFromDict(d)


import os
