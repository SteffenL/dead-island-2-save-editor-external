import base64
from dataclasses import dataclass
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Callable, List
from urllib.request import urlretrieve
from urllib.parse import urlsplit

from google.cloud import storage
import patch_ng


@dataclass
class Target:
    name: str
    version: str
    sha256: str
    filename: str
    source_subdir:  str
    url: str
    configure_options: List[str]
    cmake_subdir: str= None
    download: Callable[["Target"], None] = None
    source: Callable[["Target"], None] = None
    patch: Callable[["Target"], None] = None
    configure: Callable[["Target"], None] = None
    build: Callable[["Target"], None] = None
    install: Callable[["Target"], None] = None


def sha256sum_file(file_path: str):
    with open(file_path, "rb", buffering=0) as f:
        hash = hashlib.sha256()
        while True:
            buffer = f.read(4096)
            if len(buffer) == 0:
                break
            hash.update(buffer)
        return hash.hexdigest()


def expand_target_vars(target: Target, var: str, depth: int = 1):
    if depth > 10:
        raise Exception("Possible infinite recursion")
    replaced = var.format(
        bucket=os.getenv("GCLOUD_BUCKET"),
        filename=target.filename,
        name=target.name,
        version=target.version,
    )
    if "{" in replaced:
        return expand_target_vars(target, replaced, depth + 1)
    return replaced


def create_empty_file(file_path: str):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    open(file_path, "w").close()


ROOT_DIR = os.getcwd()
BUILD_ROOT_DIR = os.path.join(ROOT_DIR, "build")
DOWNLOAD_ROOT_DIR = os.path.join(ROOT_DIR, "download")
INSTALL_ROOT_DIR = os.path.join(ROOT_DIR, "install")
PATCH_ROOT_DIR = os.path.join(ROOT_DIR, "patch")
SOURCE_ROOT_DIR = os.path.join(ROOT_DIR, "source")


def get_download_file_path(target: Target):
    filename = expand_target_vars(target, target.filename)
    return os.path.join(DOWNLOAD_ROOT_DIR,
                        target.name, target.version, filename)


def get_source_extract_dir(target: Target):
    return os.path.join(SOURCE_ROOT_DIR, target.name, target.version)


def gcloud_download(url: str, file_path: str):
    parts = urlsplit(url)
    if parts.scheme != "gs":
        raise Exception("Unsupported scheme: {}".format(parts.scheme))
    credential_base64 = os.environ["GCLOUD_CREDENTIAL_BASE64"]
    client = storage.Client.from_service_account_info(
        json.loads(base64.b64decode(credential_base64)))
    bucket = client.bucket(parts.netloc)
    path = parts.path[1:]
    bucket.blob(path).download_to_filename(file_path)


def download(target: Target):
    if target.download == False:
        return
    if target.download:
        return target.download(target)
    url = expand_target_vars(target, target.url)
    file_path = get_download_file_path(target)
    if os.path.exists(file_path + ".ok"):
        return
    print("Downloading {} {} from {}...".format(
        target.name, target.version, url))
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if url.startswith("gs://"):
        gcloud_download(url, file_path)
    else:
        urlretrieve(url, file_path)
    digest = sha256sum_file(file_path)
    if (digest != target.sha256):
        raise Exception("Verification failed: {}".format(file_path))
    create_empty_file(file_path + ".ok")


def source(target: Target):
    if target.source == False:
        return
    if target.source:
        return target.source(target)
    extract_dir = get_source_extract_dir(target)
    if os.path.exists(extract_dir + ".extract.ok"):
        return
    print("Extracting {} {} sources...".format(target.name, target.version))
    file_path = get_download_file_path(target)
    shutil.unpack_archive(file_path, extract_dir)
    create_empty_file(extract_dir + ".extract.ok")


def patch(target: Target):
    if target.patch == False:
        return
    if target.patch:
        return target.patch(target)
    patch_file_path = os.path.join(
        PATCH_ROOT_DIR, target.name + "_" + target.version + ".patch")
    if not os.path.isfile(patch_file_path):
        return
    extract_dir = get_source_extract_dir(target)
    if os.path.exists(extract_dir + ".patch.ok"):
        return
    print("Patching {} {} sources...".format(target.name, target.version))
    subdir = expand_target_vars(target, target.source_subdir)
    source_dir = os.path.join(extract_dir, subdir) if subdir else extract_dir
    p = patch_ng.fromfile(patch_file_path)
    p.apply(strip=0, root=source_dir)
    create_empty_file(extract_dir + ".patch.ok")


def configure(target: Target):
    if target.configure == False:
        return
    if target.configure:
        return target.configure(target)
    extract_dir = get_source_extract_dir(target)
    source_dir = os.path.join(
        extract_dir, expand_target_vars(target, target.cmake_subdir if target.cmake_subdir else target.source_subdir))
    build_dir = os.path.join(BUILD_ROOT_DIR, target.name, target.version)
    if os.path.exists(build_dir + ".configure.ok"):
        return
    print("Configuring {} {}...".format(target.name, target.version))
    install_dir = INSTALL_ROOT_DIR
    link_options = []
    if platform.system() == "Linux":
        link_options.append("-static-libstdc++")
    if platform.system() == "Darwin":
        cmake_generator = "Xcode"
    else:
        cmake_generator = "Ninja"
    cmake_platform_args = []
    if platform.system() == "Darwin":
        cmake_platform_args.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=10.15")
    subprocess.check_call((
        "cmake",
        "-G",
        cmake_generator,
        "-B",
        build_dir,
        "-S",
        source_dir,
        "-DBUILD_SHARED_LIBS=OFF",
        "-DCMAKE_BUILD_TYPE=" + os.getenv("CMAKE_BUILD_TYPE", "Release"),
        "-DCMAKE_EXE_LINKER_FLAGS=" + ";".join(link_options),
        "-DCMAKE_FIND_PACKAGE_PREFER_CONFIG=TRUE",
        "-DCMAKE_INSTALL_PREFIX=" + install_dir,
        "-DCMAKE_PREFIX_PATH=" + install_dir,
        "-DCMAKE_SHARED_LINKER_FLAGS=" + ";".join(link_options),
        "-DPKG_CONFIG_USE_CMAKE_PREFIX_PATH=TRUE",
        *cmake_platform_args,
        *target.configure_options
    ))
    create_empty_file(build_dir + ".configure.ok")


def build(target: Target):
    if target.build == False:
        return
    if target.build:
        return target.build(target)
    build_dir = os.path.join(BUILD_ROOT_DIR, target.name, target.version)
    if os.path.exists(build_dir + ".build.ok"):
        return
    print("Building {} {}...".format(target.name, target.version))
    subprocess.check_call((
        "cmake",
        "--build",
        build_dir,
        "--config",
        os.getenv("CMAKE_BUILD_TYPE", "Release")
    ))
    create_empty_file(build_dir + ".build.ok")


def install(target: Target):
    if target.install == False:
        return
    if target.install:
        return target.install(target)
    build_dir = os.path.join(BUILD_ROOT_DIR, target.name, target.version)
    if os.path.exists(build_dir + ".install.ok"):
        return
    print("Installing {} {}...".format(target.name, target.version))
    subprocess.check_call((
        "cmake",
        "--install",
        build_dir,
        "--config",
        os.getenv("CMAKE_BUILD_TYPE", "Release")
    ))
    create_empty_file(build_dir + ".install.ok")


TARGETS = (
    Target(name="cereal",
           version="1.3.2",
           sha256="16a7ad9b31ba5880dac55d62b5d6f243c3ebc8d46a3514149e56b5e7ea81f85f",
           filename="v{version}.tar.gz",
           source_subdir="cereal-{version}",
           url="https://github.com/USCiLab/cereal/archive/refs/tags/{filename}",
           configure_options=(
               "-DBUILD_TESTS=OFF",
               "-DBUILD_DOC=OFF",
               "-DBUILD_SANDBOX=OFF",
               "-DSKIP_PERFORMANCE_COMPARISON=ON",
           )),
    Target(name="cityhash",
           version="f5dc54147fcce12cefd16548c8e760d68ac04226", # v1.1 with unreleased fixes
           sha256="20ab6da9929826c7c81ea3b7348190538a23f823a8b749c2da9715ecb7a6b545",
           filename="{version}.zip",
           source_subdir="cityhash-{version}",
           url="https://github.com/google/cityhash/archive/{filename}",
           configure_options=()),
    Target(name="cli11",
           version="2.3.2",
           sha256="aac0ab42108131ac5d3344a9db0fdf25c4db652296641955720a4fbe52334e22",
           filename="v{version}.tar.gz",
           source_subdir="CLI11-{version}",
           url="https://github.com/CLIUtils/CLI11/archive/refs/tags/{filename}",
           configure_options=(
               "-DCLI11_SINGLE_FILE=OFF",
               "-DCLI11_PRECOMPILED=ON",
               "-DCLI11_BUILD_DOCS=OFF",
               "-DCLI11_BUILD_TESTS=OFF",
               "-DCLI11_BUILD_EXAMPLES=OFF",
               "-DCLI11_SINGLE_FILE_TESTS=OFF",
               "-DCLI11_INSTALL=ON",
               "-DCLI11_CUDA_TESTS=OFF",
           )),
    Target(name="msgpack",
           version="6.0.0",
           sha256="0948d2db98245fb97b9721cfbc3e44c1b832e3ce3b8cfd7485adc368dc084d14",
           filename="msgpack-cxx-{version}.tar.gz",
           source_subdir="msgpack-cxx-{version}",
           url="https://github.com/msgpack/msgpack-c/releases/download/cpp-{version}/{filename}",
           configure_options=(
                "-DMSGPACK_CXX20=ON",
                "-DMSGPACK_BUILD_DOCS=OFF",
                "-DMSGPACK_USE_BOOST=OFF",
           )),
    Target(name="rapidcsv",
           version="8.75",
           sha256="004454890d371b4db370dfd44d64077f8f9b2b92e59d1d6471e1923f891485be",
           filename="v{version}.tar.gz",
           source_subdir="rapidcsv-{version}",
           url="https://github.com/d99kris/rapidcsv/archive/refs/tags/{filename}",
           configure_options=()),
    Target(name="zstd",
           version="1.5.5",
           sha256="9c4396cc829cfae319a6e2615202e82aad41372073482fce286fac78646d3ee4",
           filename="zstd-{version}.tar.gz",
           source_subdir="zstd-{version}",
           url="https://github.com/facebook/zstd/releases/download/v{version}/{filename}",
           configure_options=(
               "-DZSTD_LEGACY_SUPPORT=OFF",
               "-DZSTD_BUILD_PROGRAMS=OFF",
               "-DZSTD_BUILD_STATIC=ON",
               "-DZSTD_BUILD_SHARED=OFF",
               "-DZSTD_BUILD_TESTS=OFF",
           ),
           cmake_subdir="zstd-{version}/build/cmake"),
)

STAGES = (download, source, patch, configure, build, install)


def main(args: List[str]):
    known_target_names = set([target.name for target in TARGETS])
    for target_name in args:
        if not target_name in known_target_names:
            raise Exception("Unknown target: {}".format(target_name))
    for target in TARGETS:
        for stage in STAGES:
            if len(args) == 0 or target.name in args:
                stage(target)


if __name__ == "__main__":
    main(sys.argv[1:])
