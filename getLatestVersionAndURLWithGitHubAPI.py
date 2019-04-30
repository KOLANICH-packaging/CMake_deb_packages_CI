#!/usr/bin/env python3
import sys
from datetime import datetime
from dateutil.parser import parse as parseDT
import requests
import shlex
import datetime
import re
import typing


GH_API_BASE = "https://api.github.com/"

class ComparableDownloadTarget:
	def cmpTuple(self) -> tuple:
		raise NotImplementedError()
	
	def __lt__(self, other):
		return self.cmpTuple() < other.cmpTuple()

	def __gt__(self, other):
		return self.cmpTuple() > other.cmpTuple()

	def __eq__(self, other):
		return self.cmpTuple() == other.cmpTuple()

class DownloadTargetFile(ComparableDownloadTarget):
	__slots__ = ("created", "modified", "uri", "role")
	def __init__(self, role: typing.Optional[str], created: datetime, modified: datetime, uri: str):
		self.created = created
		self.modified = modified
		self.uri = uri
		self.role = role

	def cmpTuple(self):
		return (self.created, self.modified)

	def __str__(self):
		return self.role + "<" + self.uri + ">"



class DownloadTarget(ComparableDownloadTarget):
	def __init__(self, name: str, version: str, prerelease: bool, created: datetime, published: datetime, files: typing.Dict[typing.Optional[str], DownloadTargetFile]):
		self.name = name
		self.version = version
		self.prerelease = prerelease
		self.created = created
		self.published = published
		self.files = files

	def cmpTuple(self):
		return (self.created, self.published)

	def __str__(self):
		return self.name + " (" + self.version + ", " + ("pre" if self.prerelease else "") + "release" + ") <" + repr(self.files) + ">"



def getTargets(repoPath, titleRx, tagRx, downloadFileNamesRxs, signed=False):
	if not isinstance(downloadFileNamesRxs, dict):
		downloadFileNamesRxs = {None: downloadFileNamesRxs}
	
	RELEASES_EP = GH_API_BASE + "repos/" + repoPath + "/releases"

	req = requests.get(RELEASES_EP)
	headers = requests.utils.default_headers()
	h = req.headers
	limitRemaining = int(h["X-RateLimit-Remaining"])
	limitTotal = int(h["X-RateLimit-Limit"])
	limitResetTime = datetime.datetime.utcfromtimestamp(int(h["X-RateLimit-Reset"]))

	print(limitRemaining, "/", limitTotal, str((limitRemaining / limitTotal)*100.)+"%", "limit will be reset:", limitResetTime, "in", limitResetTime - datetime.datetime.now())

	t = req.json()
	#print(t)

	if isinstance(t, dict) and "message" in t:
		raise Exception(t["message"])
	

	for r in t:
		nm = r["name"]
		if titleRx is not None and not titleRx.match(nm):
			continue
		#print(r["tag_name"], tagRx.match(r["tag_name"]))
		tagMatch = tagRx.match(r["tag_name"])

		if not tagMatch:
			continue

		pr = r["prerelease"]
		v = tagMatch.group(1)
		#print("tagMatch.group(1)", tagMatch.group(1))
		c = parseDT(r["created_at"])
		#print("c", c)
		p = parseDT(r["published_at"])
		#print("p", p)
		files = {}
		for a in r["assets"]:
			for role, downloadFileNameRx in downloadFileNamesRxs.items():
				#print(a["name"], downloadFileNameRx.match(a["name"]))
				if not downloadFileNameRx.match(a["name"]):
					continue
				fc = parseDT(a["created_at"])
				m = parseDT(a["updated_at"])
				files[role] = DownloadTargetFile(role, fc, m, a["browser_download_url"])
		#print(files, len(files), len(downloadFileNamesRxs), len(files) == len(downloadFileNamesRxs))
		if len(files) == len(downloadFileNamesRxs):
			yield DownloadTarget(nm, v, pr, c, p, files)
		
