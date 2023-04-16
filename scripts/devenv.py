from enum import Enum
import os
import platform
import subprocess
import sys
from typing import List


class Arch(Enum):
    ARM64 = "arm64"
    ARM32 = "arm32"
    X64 = "x64"
    X86 = "x86"


ARCH_TO_MSVC_COMPONENT_ARCH_MAP = {
    Arch.X64: "x86.x64",
    Arch.X86: "x86.x64",
    Arch.ARM64: "ARM64",
    Arch.ARM32: "ARM"
}


ARCH_TO_VCVARS_ARCH_MAP = {
    Arch.X64: "x64",
    Arch.X86: "x86",
    Arch.ARM64: "arm64",
    Arch.ARM32: "arm"
}


def find_vcvars(target_arch: Arch):
    python_arch_bits, _ = platform.architecture()
    if python_arch_bits == "64bit":
        pf_path_x86 = os.environ["ProgramFiles(x86)"]
    elif python_arch_bits == "32bit":
        pf_path_x86 = os.environ["ProgramFiles"]
    else:
        raise Exception("Unsupported architecture")
    vswhere_rel_path_parts = (
        "Microsoft Visual Studio", "Installer", "vswhere.exe")
    vswhere_path_x86 = os.path.join(pf_path_x86, *vswhere_rel_path_parts)
    if os.path.exists(vswhere_path_x86):
        vswhere_path = vswhere_path_x86
    else:
        raise Exception("Unable to find vswhere.exe")
    msvc_arch_component_suffix = ARCH_TO_MSVC_COMPONENT_ARCH_MAP[target_arch]
    vswhere_args = (vswhere_path, "-latest", "-products", "*", "-requires",
                    "Microsoft.VisualStudio.Component.VC.Tools." + msvc_arch_component_suffix,
                    "-property", "installationPath")
    vs_dir = subprocess.check_output(vswhere_args, encoding="utf8").strip()
    vcvars_path = os.path.join(
        vs_dir, "VC", "Auxiliary", "Build", "vcvarsall.bat")
    if not os.path.exists(vcvars_path):
        raise Exception("Unable to find vcvarsall.bat")
    return vcvars_path


def activate_msvc_toolchain(architecture: Arch, vcvars_version: str):
    vcvars_arch = ARCH_TO_VCVARS_ARCH_MAP[architecture]
    vcvars_path = find_vcvars(architecture)
    # Extract environment variables set by vcvars.
    vcvars_args = ("cmd.exe", "/C", "call", vcvars_path, vcvars_arch,
                   "-vcvars_ver=" + vcvars_version, ">", "nul", "&&", "set")
    vcvars_output_bytes = subprocess.check_output(vcvars_args)
    vcvars_output = vcvars_output_bytes.decode("utf-8").strip()
    vcvars_env = tuple(kv.split("=", 1) for kv in vcvars_output.splitlines())
    # Temporarily update the current environment with the variables extracted from vcvars.
    os.environ.update(vcvars_env)


def main(args: List[str]):
    cmd = None
    if platform.system() == "Windows":
        arch, vcvars_version = (os.environ["VCVARS_ARCH"],
                                os.environ["VCVARS_VERSION"])
        activate_msvc_toolchain(Arch(arch), vcvars_version)
        args = tuple(arg.replace("^", "^^").replace('"', '^"') for arg in args)
        args_string = " ".join(
            tuple(('"{}"'.format(arg) if " " in arg else arg) for arg in args))
        cmd = ("cmd.exe", "/C", args_string)
    else:
        args = tuple(arg.replace("\\", "\\\\").replace('"', '\\"')
                     for arg in args)
        args_string = " ".join(
            tuple(('"{}"'.format(arg) if " " in arg else arg) for arg in args))
        cmd = ("sh", "-c", args_string)
    subprocess.check_call(cmd)


if __name__ == "__main__":
    main(sys.argv[1:])
