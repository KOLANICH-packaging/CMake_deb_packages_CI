Scripts for building Debian/Ubuntu packages for CMake
=====================================================

Scripts in this repo are [Unlicensed ![](https://raw.githubusercontent.com/unlicense/unlicense.org/master/static/favicon.png)](https://unlicense.org/).

Third-party components have own licenses.

**DISCLAIMER: BADGES BELOW DO NOT REFLECT THE STATE OF THE DEPENDENCIES IN THE CONTAINER**

The software in this repo builds a set of packages from prebuilt binaries of Oracle (TM) GraalVM.
The licenses of the software is available by official links and are also included into the packages.

Artifacts of CI builds can be used as a repo for apt.

```bash
export ARTIFACTS_PATH=https://kolanich.gitlab.io/CMake_deb_packages_CI
export KEY_FINGERPRINT=898bad1e937da3e70035b48a27805fb291a720d1
curl -o public.gpg $ARTIFACTS_PATH/public.gpg
apt-key add public.gpg
echo deb [arch=amd64,signed-by=$KEY_FINGERPRINT] $ARTIFACTS_PATH/repo cosmic contrib >> /etc/apt/sources.list.d/vanilla_CMake_KOLANICH.list
apt update
```

Setting up an own repo
==================

1. generate a GPG private key

2. export it
```bash
gpg --no-default-keyring --keyring ./kr.gpg --export-secret-key $KEY_FINGERPRINT | base64 -w0 > ./private.gpg.b64
```
`-w0` is mandatory.

3. paste it into GitLab protected environment variable `GPG_KEY`
