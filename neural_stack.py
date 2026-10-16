# DLSS 5 Neural Lens: the stack setup.
# Copyright (C) 2026 Leaps-Bounds
#
# Licensed under the PolyForm Strict License 1.0.0, whose text is in the LICENSE
# file beside this one.
"""Fetch and assemble the DLSS Neural Rendering stack the lens drives.

Nothing of the stack is bundled. Every component is downloaded from the
project that publishes it, into the lens's own folder, and registered for the
current user only, so no elevation is needed and nothing shared with other
software is touched. Licences force this: NVIDIA's runtimes are NVIDIA's, the
RenoDX add-on has no published licence, and a new install gets
ReshadeMotionEstimation (CC BY-NC 4.0) for motion vectors, chosen by
measurement, with VORT (MIT, its motion vector code CC BY-NC 4.0) as the
alternative.

What ends up where. APP is the lens's own folder. TARGET, the stack folder, is
APP itself for the installed program and APP\\stack when run from source:

    TARGET\\lens-presenter.exe                  installed, part of the program; from
                                               source, a copy of the Python running this
    TARGET\\pyvenv.cfg, Lib\\site-packages\\lens-presenter.pth   from source only
    TARGET\\nvngx_dlss.dll                      NVIDIA, via the RHI manifest
    TARGET\\nvngx_dlssnr_real.dll               NVIDIA's Neural Rendering model: on an RTX 50 card the
                                               310.9.16 model from NVIDIA's own package, which holds
                                               the large network (preset A) and the small FP8 network
                                               (preset B), and on an older card, or where that
                                               package cannot be had, the 310.8.SF-v2 build via
                                               the RHI manifest, see step_nvidia
    TARGET\\NVIDIA-RTX-SDK-LICENSE.txt          NVIDIA's licence, out of the same package, beside the
                                               310.9.16 model alone
    TARGET\\nvngx_dlssnr.dll, nvngx_dlssnr.ini  DLSSNR-Cost-Scaler, the proxy in front of it
    TARGET\\dlss5-feed.addon64                  DLSS5-Feeder
    TARGET\\renodx-dlss5.addon64                RenoDX, via the RHI repository, the build chosen
    TARGET\\addons\\renodx-dlss5_*.zip           both builds as fetched, and each one's copy of
                                               its section of ReShade.ini, see ADDON_BUILDS
    TARGET\\RenoDX-DLSS5-crash.log              the 8.5 build's own journal, see addon_journal_trim
    TARGET\\reshade-shaders\\Shaders\\...        DLSS5_Feed.fx, DRME, VORT, ReShade headers
    TARGET\\ReShade.ini, ReShadePreset.ini, dlss5-feed.cfg
    TARGET\\install-record.json                 everything above, for uninstall
    TARGET\\fast\\lens-fast.exe                 the fast engine, installed with the program and
                                               never written here. From source the lens runs the
                                               one fast_engine\\build.cmd builds in fast_engine\\bin
    TARGET\\fast\\nvngx_dlssnr.ini              the fast engine's own copy of the proxy's ini,
                                               written beside its exe, in fast_engine\\bin from
                                               source. --uninstall removes it and the engine's logs
    APP\\ReShade\\ReShade64.dll, ReShade64.json, ReShadeApps.ini
    APP\\downloads\\...                           while installing; removed once the self test passes.
                                               NVIDIA's package and the two files taken out of it
                                               in a folder of their own there, nvidia-dlnr
    HKCU\\SOFTWARE\\Khronos\\Vulkan\\ImplicitLayers\\<APP\\ReShade\\ReShade64.json> = 0

The stack folder has to be the folder lens-presenter.exe is in. ReShade reads
its configuration from the executable's own folder: started from elsewhere with
the stack as its working directory, the layer did not attach, measured.

A DLL the user points at is hash checked and copied in; the record names the
copy, so uninstalling never touches the original.

The layer is registered under a name of its own, VK_LAYER_reshade_neural_lens,
and switches on only in a process that sets ENABLE_VK_LAYER_reshade_neural_lens=1,
which the presenter does for itself. The Vulkan loader loads one layer per name,
so a copy named like a machine wide ReShade would be skipped where one exists,
and this way the two coexist. ReShade itself starts in any program with a
ReShade.ini in its own folder, whatever ReShadeApps.ini says, so without that
switch the lens's copy could start in place of another program's own ReShade.
Releases up to 0.5.1 had no such switch. The lens checks the switch as it
starts, and --verify says whether it is there, see layer_ungated.

The add-on's section of ReShade.ini starts with its ConfigVersion and NRPreset=1,
so a new install runs the add-on's own defaults, apart from two that the lens
sets before its presenter starts, where the section holds no value for them:
chained temporal history on, and the Classic codec. A repair keeps that section,
and the lens's own section byte for byte, see step_config.

NRPreset chooses the network of the 310.9.16 model, as both engines hand it to
the model: 1 the large network (preset A), which every earlier model ran, and
2 the small FP8 network (preset B), as the lens's Model setting writes them.
That model runs the small FP8 network at 0, the add-on's default, too. So once,
where the section holds 0 or no NRPreset, the setup writes 1 and says so, see
step_config, and the lens writes 1 before its presenter starts where the
section has lost it. The 310.8 builds hold the large network alone and draw
the same picture at 0, 1 and 2, measured.

Command line, for testing and for people who prefer it:

    python neural_stack.py                  install into the default folder
    python neural_stack.py --target D:\\nr   install somewhere else, from source
    python neural_stack.py --dlssnr X --dlss Y   use NVIDIA DLLs you already have (hash checked)
    python neural_stack.py --provider vort  estimate motion vectors with VORT instead of DRME
    python neural_stack.py --verify         only run the self test on an existing stack, and
                                            check that the layer is limited to the lens
    python neural_stack.py --uninstall      remove what the record says was installed

The installer runs this during setup. The lens offers it again if it starts
without a stack, and the Start Menu's stack setup entry runs it on demand.

The Neural Rendering add-on is one of two builds, 5.2.1 by default or
8.5.0-rc10, which the lens calls the Home menu add-on. Both are fetched into the
stack's addons folder and the chosen one is put in place, with its section of
ReShade.ini in that build's schema, and under the 8.5 build the lens also turns
its Independent skin off where the section holds no value for it, see
ADDON_BUILDS, step_renodx and addon_switch. The command line takes the choice
as --addon 5.2.1 or --addon 8.5, and without it the setup takes the lens's own,
see addon_choice.
"""
import hashlib
import json
import lzma
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import winreg
import zipfile
import zlib

__version__ = "0.9.0"

FROZEN = getattr(sys, "frozen", False)
# Everything lives in the lens's own folder, the one the installer put it in or
# the one this script is in: the stack, the ReShade layer, the downloads while
# they are needed, and (in neural_lens.py) the state and logs. Uninstalling is
# then removing that one folder plus the registry value that names it.
APP_DIR = (os.path.dirname(sys.executable) if FROZEN
           else os.path.dirname(os.path.abspath(__file__)))
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW, for console children of a windowless lens
DEFAULT_TARGET = APP_DIR if FROZEN else os.path.join(APP_DIR, "stack")
LAYER_DIR = os.path.join(APP_DIR, "ReShade")
CACHE_DIR = os.path.join(APP_DIR, "downloads")
LAYER_NAME = "VK_LAYER_reshade_neural_lens"
LAYER_GATE = "ENABLE_VK_LAYER_reshade_neural_lens"     # the switch the layer waits for, see layer_ungated
LAYER_KEY = r"SOFTWARE\Khronos\Vulkan\ImplicitLayers"

# What the download comes to, for the installer's page, the wizard and the
# lens's offer: ReShade's setup 4 MB, NVIDIA's two runtimes 29 and 111 MB as the
# manifest serves them zipped, and everything else under 2 MB together. On a
# card that gets NVIDIA's own package for its model, see NVIDIA_PACKAGE, that
# package's 351 MB come in place of the 111, see download_mb.
DOWNLOAD_MB = 150
DOWNLOAD_MB_PACKAGE = 390

RESHADE_VERSION = "6.8.0"
RENODX_VERSION = "5.2.1"
COST_SCALER_VERSION = "1.0.6"
SOURCES = {
    "reshade": "https://reshade.me/downloads/ReShade_Setup_%s_Addon.exe" % RESHADE_VERSION,
    "manifest": "https://raw.githubusercontent.com/RankFTW/RHI/main/dlss_manifest.json",
    "rhi_release": "https://github.com/RankFTW/rhi-repo/releases/download/%s/%s",
    "feeder_api": "https://api.github.com/repos/jlrouzies-fr/DLSS5-Feeder/releases/latest",
    "renodx": ("https://github.com/RankFTW/rhi-repo/releases/download/renodx-dlss5-%s/renodx-dlss5_%s.zip"
               % (RENODX_VERSION, RENODX_VERSION)),
    "cost_scaler": ("https://github.com/xenmods/DLSSNR-Cost-Scaler/releases/download/v%s/DLSSNR-Cost-Scaler-v%s.zip"
                    % (COST_SCALER_VERSION, COST_SCALER_VERSION)),
    "vort": "https://raw.githubusercontent.com/vortigern11/vort_Shaders/main/",
    "vort_api": "https://api.github.com/repos/vortigern11/vort_Shaders/contents/Shaders/Includes",
    # ReshadeMotionEstimation by Jakob Wapenhensch, CC BY-NC 4.0, pinned to its
    # last commit since the repository publishes no releases
    "drme": "https://raw.githubusercontent.com/JakobPCoder/ReshadeMotionEstimation/5fc3f434ba15/",
    "headers": "https://raw.githubusercontent.com/crosire/reshade-shaders/slim/Shaders/",
}
DRME_FILES = ["MotionEstimation.fx", "MotionEstimation.fxh", "MotionEstimationUI.fxh", "MotionVectors.fxh"]
# Which shader estimates motion vectors for the Feed. Measured on scrolling
# text as the partial ink fraction of the page, lower is crisper, at a slow,
# a reading and a fast scroll: DRME 0.075, 0.096, 0.102; VORT 0.099, 0.109,
# 0.106; no provider 0.114, 0.123. DRME is CC BY-NC 4.0, so it may be fetched
# and used with credit in a free tool and is the default. VORT is MIT apart
# from its motion vector code, which builds on DRME and is CC BY-NC 4.0 too,
# and stays as the alternative.
PROVIDERS = {"drme": 0, "vort": 2}
# vort_Motion.fx pulls in most of its Includes folder through nested includes
# (Depth, ColorTex, BlueNoise, Tonemap and more, four of which a hand picked
# list once missed, so the shader failed to compile and the Feed fell back to
# zero motion vectors). The whole folder is fetched, plus the blue noise
# texture the motion pass samples.
VORT_TEXTURES = ["vort_BlueNoise.png"]
HEADER_FILES = ["ReShade.fxh", "ReShadeUI.fxh"]

# The manifest carries no hashes, so these are held here. Every one was measured
# on a working install and its file ran Neural Rendering; a download that
# matches none is refused, not installed. The 310.8.SF-v2 entry accepts two
# known builds: the one the repository serves (version 310.8.SF.0, 165,830,144
# bytes) and an earlier community build (165,840,496 bytes, version 310.8.0.0)
# that many people already hold. The add-on and the Cost Scaler are pinned
# releases, so both their archives and the files taken out of them are checked.
DLSS_VERSION = "310.8.0"
HASHES = {
    "nvngx_dlss.dll": ["c85f971ce023c9f3492fc7455f0b01a24ba18ea39636407a846902c4360b0b7e"],
    "nvngx_dlssnr.dll": {
        "310.8.0": ["e16bcf15e16e13f527491cdf7845b2fe6521a738d8f7c9c721866a8496e1fc8e"],
        "310.8.SF-v2": ["6eb209e764f39872625debd6abaf45e2bb6322f6f270f781f70c059ae30b3927",
                        "8270b350cd82de5ce89806872cdd6b6a9249b80836b91bbeb3573470744cc206"],
    },
    "renodx-dlss5.zip": ["125506b22edd8e0d6f8117579fe2a516288440fc068a5310680065db5d027129"],
    "renodx-dlss5.addon64": ["a1b78052b58fc285f018362ac8652df8a01d31be9f3ecbb9e31776866ead5887"],
    "cost-scaler.zip": ["525cc45b00dcb1ba03ce6c25905ff02c3ff3458b5e90ebf4138b307f46e13095"],
    # the Feed's zip is normally checked against the SHA-256 its release notes
    # print; these are the ones verified by hand, for a release whose notes
    # leave it out
    "dlss5-feeder.zip": ["0d1deebf531436a6d0914548e450a790aefa53cb4e9f6dfdcd48aff74831cb21"],
    "cost-scaler.dll": ["975b0a063b32463a8812209810f338f3025b47b97d7cb621330c11a7d13898e8"],
}
# The SF-v2 build serves every RTX card. It was thought to be 40 series only
# until it was measured running on an RTX 5090 on 2026-09-12: feature 18 created
# and evaluated, and the in-to-out difference matched the stock model to within
# 0.01 at two pinned rates. Its author states it covers RTX 20, 30 and 40 and
# runs identically on 50. It is the model on a card older than the RTX 50
# series, and on any card where NVIDIA's package below cannot be had. The stock
# 310.8.0 hash is listed for identification only: step_nvidia accepts the
# builds of MODEL and NVIDIA_MODEL and nothing else.
MODEL = "310.8.SF-v2"

# NVIDIA's own package of its Neural Rendering model, as NVIDIA's RTX Remix
# names it on GitHub: packman-external.xml on main has
# <package name="rtx-remix-ngx_sdk_dlnr" version="2" />, and
# scripts-common/packman/external_config.packman.xml the link it is fetched by,
# https://d1oqksizpb0e3d.cloudfront.net/${name}@${version}. It is a 7z archive,
# read by read_7z, and holds the model for x86_64 and Arm, NVIDIA's licence and
# the model's headers. Its model, nvngx_dlssnr.dll 310.9.16, signed by NVIDIA,
# holds two networks, chosen by the preset the features are created with, see
# MODEL_KEY: preset 1 (A) runs the large network, byte for byte the pictures of
# the 310.8.SF-v2 build, and 0, 2 (B) and 3 the small FP8 network, which
# NVIDIA names for the RTX 50 series and RTX Spark laptops. Measured on an RTX
# 5090 on 2026-10-16, see docs/NOTES.md, NVIDIA's model package. Nothing of the
# package was tried on an older card, where the SF-v2 build is known to run. So
# the package is fetched for a card of compute capability NVIDIA_FROM_CAPABILITY
# or higher, Blackwell's RTX 50 series, and every older card keeps MODEL.
NVIDIA_MODEL = "310.9.16"
NVIDIA_PACKAGE = {
    "url": "https://d1oqksizpb0e3d.cloudfront.net/rtx-remix-ngx_sdk_dlnr@2.7z",
    "name": "rtx-remix-ngx_sdk_dlnr@2.7z",
    "size": 367851723,
    "sha256": ["4bb8651b3ac2180f23df1f39422c489810a13d445a94dc836c876c18c93ecefe"],
    "model": "lib/Windows_x86_64/rel/nvngx_dlssnr.dll",
    "model_size": 266424944,
    "licence": "LICENSE.txt",
}
HASHES["nvngx_dlssnr.dll"][NVIDIA_MODEL] = ["2bc19bc09a7b89dd44f73e2ac0108fcc586e2154bdd0830f242f4f040e28789f"]
NVIDIA_FROM_CAPABILITY = 12.0
# NVIDIA's licence, the package's LICENSE.txt, goes into the stack folder beside
# the model it came with, under this name, and only there
NVIDIA_LICENCE = "NVIDIA-RTX-SDK-LICENSE.txt"
# the package's own folder among the downloads, in CACHE_DIR as it is when the
# package is fetched, so a caller that moves the downloads moves it too
PACKAGE_FOLDER = "nvidia-dlnr"
# The model's network is NRPreset in the add-on's section, the preset both
# engines create the features with: LARGE, the large network (preset A),
# which every model before 310.9.16 ran and which a new install starts with, or
# SMALL, the small FP8 network (preset B), as the lens's Model setting writes
# them. The names in the code are the ones the lens gave the networks first,
# and the setup's lines name them by LARGE_SAID and SMALL_SAID, set here alone.
# 0, the add-on's default, runs the small FP8 network on 310.9.16, so the setup
# writes LARGE once where the section holds 0 or no NRPreset, and the
# install record keeps PRESET_DONE so it is done once.
MODEL_KEY = "NRPreset"
LARGE, SMALL = "1", "2"
LARGE_SAID, SMALL_SAID = "the large network (preset A)", "the small FP8 network (preset B)"
PRESET_DONE = "model_preset_written"

# The Cost Scaler is written with its own settings apart from these. The lens
# switches the proxy on for fullscreen and off when windowed, so it starts off.
# Its hotkeys are polled globally, and a desktop program must not answer
# Ctrl+Alt+PageUp in every window. Its depth aware resolve works from the depth
# the Feed synthesises for content that has none, and every measurement of the
# proxy in the lens was taken with it off.
COST_SCALER_SETTINGS = {"EnableProxy": "0", "EnableHotkeys": "0",
                        "EnableDepthAwareResolve": "0", "EnableGovernor": "0"}

RESHADE_INI = """[ADDON]
AddonPath=.\\

[GENERAL]
EffectSearchPaths=.\\reshade-shaders\\Shaders
TextureSearchPaths=.\\reshade-shaders\\Textures
PresetPath=.\\ReShadePreset.ini
NoDebugInfo=1
NoEffectCache=0
NoReloadOnInit=0
PerformanceMode=0
PreprocessorDefinitions=RESHADE_DEPTH_LINEARIZATION_FAR_PLANE=1000.0,RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN=0,RESHADE_DEPTH_INPUT_IS_REVERSED=0,RESHADE_DEPTH_INPUT_IS_LOGARITHMIC=0,DLSS5_MV_PROVIDER=2,V_MV_MODE=1

[INPUT]
ForceShortcutModifiers=1
InputProcessing=2
KeyOverlay=36,0,0,0
KeyScreenshot=44,0,0,0

[OVERLAY]
AutoSavePreset=1
ShowFPS=0
ShowFrameTime=0
TutorialProgress=4

[RenoDX.DLSS5]
ConfigVersion=2
NRPreset=1

[SCREENSHOT]
SavePath=.\\
FileFormat=1
"""
# The add-on resets its whole section to its built-in defaults when ConfigVersion
# is missing or older than its own, and otherwise fills any key that is absent
# with its default. Measured with 5.2.1 and this section alone: it ran at its
# defaults, wrote back EnableHooks=2, NeuralUplift=1 and NREnableUpscaling=0,
# and feature 18 created and evaluated. NRPreset=1 is the large network, see
# MODEL_KEY.
ADDON_SECTION = "[RenoDX.DLSS5]"
# 5.2.1 resets on any ConfigVersion other than its own 2, a newer one included:
# on a section the 8.5 build had written at 7 it logged "config schema v7 is
# stale (current v2); applying the built-in defaults" and wrote its defaults
# over every value. The 8.5 build, whose own is 7, migrates a section of another
# ConfigVersion key by key, keeping the values, after a copy of ReShade.ini
# beside it named ReShade.ini.renodx-dlss5-pre-v4-migration- with the date and
# time, and pins NRPQCalibration at 2.5375 where a section of its own gets 1. So
# the template's 2 is 5.2.1's, and for the 8.5 build the setup gives a new
# install a section at 7, see step_renodx.
#
# The Home menu add-on: two builds of the RenoDX DLSS 5 add-on, each fetched
# from its release on the RHI repository and checked by hash, the zip and the
# add-on in it. 5.2.1 is the default. 8.5.0-rc10 is a release candidate of the
# 8.5 line, the last build of the add-on made public, with a larger Home menu.
# Measured in the presenter on 2026-10-05, on a test computer with an RTX 5090:
# the same still picture as 5.2.1, 0.21 of 255 apart, the harnesses whole, and
# 2.6 percent off the ReShade engine's frame rate over the whole monitor at one
# pass, which is its Detail stability filter, on by default, and with it Off as
# fast as 5.2.1. It draws a notice of its own, "Neural Rendering is active", at
# the top left of the picture for about four seconds at every presenter start,
# and keeps a journal beside the presenter, ADDON_JOURNAL, a few lines each
# start, see addon_journal_trim.
#
# The choice is the lens's, addon in neural-lens.ini, 8.5 or nothing for 5.2.1,
# see addon_choice. The setup fetches both zips into ADDON_DIR in the stack
# folder, where they stay, and puts the chosen build's add-on in place as
# renodx-dlss5.addon64. The lens swaps it there when the choice changes, before
# a presenter starts, see addon_switch.
#
# Each build reads its own schema of the section, schema being the ConfigVersion
# it writes. A switch keeps the section as it was in ADDON_DIR as the copy of
# the build it was written for, and gives the build that comes the values both
# builds read, from the section as it was, and the rest from that build's own
# copy, see section_convert. So neither build finds the other's ConfigVersion,
# 5.2.1 never resets and the 8.5 build never migrates.
#
# The lens gives the 8.5 build one value of its own where its section holds
# none, NRSkinIndependent=0, Independent skin off, which sends Structure and
# Character / skin as they are, as 5.2.1 does. Its default, on, sends Structure
# at most 1 while the Character mask is on, so a look with the mask on and
# Structure above 1 would change with the build, see _write_addon_settings in
# neural_lens.py. Detail stability keeps its default, Auto, which filters the
# network's change over frames along the motion vectors to keep fine detail
# steady.
ADDON_BUILDS = {
    "5.2.1": {"version": RENODX_VERSION, "schema": "2", "url": SOURCES["renodx"],
              "zip": HASHES["renodx-dlss5.zip"], "addon": HASHES["renodx-dlss5.addon64"]},
    "8.5": {"version": "8.5.0-rc10", "schema": "7",
            "url": SOURCES["rhi_release"] % ("renodx-dlss5-8.5.0-rc10", "renodx-dlss5_8.5.0-rc10.zip"),
            "zip": ["a745040cb2e93e3a1500a6c5a322972acc4c5c667108fcea31c748285d6364a9"],
            "addon": ["dcd93881e976ad033d83c2bb01f4bc3e4ddc59c15fe0dd4ca165bc5fc7d1ac68"]},
}
ADDON_DEFAULT = "5.2.1"
ADDON_DIR = "addons"
ADDON_JOURNAL = "RenoDX-DLSS5-crash.log"
ADDON_JOURNAL_MOST = 64 * 1024
ADDON_BACKUP = "ReShade.ini.renodx-dlss5-"     # how each copy of ReShade.ini the 8.5 build makes is named
# The keys of the section both builds read with one meaning, which a switch
# takes from the section as it is, by the key names in the two files and the
# 8.5 build's source. 5.2.1 reads two more, NRAdaptiveExposure and NRPreUpscale,
# and the 8.5 build about a hundred more. NREnableUpscaling is the Feed's, which
# neither build reads and the Feed writes and keeps, and NRKeepBlacks the fast
# engine's, which neither build reads either.
# Skin structure goes from -1 to 1 under the 8.5 build, which runs a value above
# 1 at 1, so such a value goes to it as 1, and comes back to 5.2.1 as its own
# copy has it while the 8.5 build has left it at 1. The codec is 0 Classic or 1
# Anchored under 5.2.1, and the 8.5 build adds 2 Auto and 3 Display, which go
# back to 5.2.1 as its copy has the codec.
ADDON_SHARED = ("EnableHooks", "NeuralUplift", "NRAutoMask", "NRChainedHistory", "NRCodecMode", "NRColorStrength",
                "NRDepthMode", "NRDiffuseWhiteNits", "NREnableUpscaling", "NRFollowInputRes", "NRGlobalTone",
                "NRIntensity", "NRLocalStructure", "NRLocalTone", "NRMaxWorksets", "NRMVecScaleX", "NRMVecScaleY",
                "NRPaperWhiteScale", "NRPass2Color", "NRPass2Intensity", "NRPass3Color", "NRPass3Intensity",
                "NRPass4Color", "NRPass4Intensity", "NRPasses", "NRPreset", "NRProxyAnchor", "NRResolutionScale",
                "NRScreenshotKey", "NRSkinStructure", "NRStyle", "NRToggleKey", "NRTransferStrength",
                "NRUICorrection",
                # the Look stage's keys, which the 8.5 build and the fast engine read and 5.2.1 leaves
                # alone, and Keep blacks, NRKeepBlacks, which the fast engine alone reads, so a fullscreen
                # lens keeps its look whichever build the window runs, see LOOK_KEYS in neural_lens.py
                "NRDetailStability", "NRKeepBlacks", "NRLookMode", "NRLookTone", "NRLookDetail",
                "NRLookDetailRadius", "NRLookHalo", "NRLookHaloBrightSide", "NRLookStabilize", "NRLookStabilizeMs",
                "NRLookStabilizeDetail", "NRLookMaxBrighten", "NRLookMaxDarken", "NRLookMaxColour")
# Before upscaling, "Denoise before upscaling" in 5.2.1's Home menu, is
# NRPreUpscale, 0 or 1. Under the 8.5 build it is the hook point, NRHookPoint,
# 0 Upscaled, 1 Render, the same path with the same picture, or 2 Present,
# which the 8.5 build never serves in a program that presents through Vulkan,
# as the presenter does, and runs as Upscaled, so it goes to 5.2.1 as 0.
ADDON_HOOK = {"5.2.1": "NRPreUpscale", "8.5": "NRHookPoint"}
# The lens's own section, which the add-on never reads. It holds the values a
# pass from the second on has of its own, which of passes 2 to 4 are ticked
# Same as pass 1, SharedNetwork, whether the passes after the first run through
# the first pass's network on the fast engine, and ScaleChange with Strength,
# whether and how much that engine scales the network's change. The name is
# PASS_SECTION in neural_lens.py and kPassSection in the fast engine. The
# template has no such section, and a new install starts without one, so each
# pass starts out on a network of its own and the change not scaled.
LENS_SECTION = "[NeuralLens.Passes]"
RESHADE_PRESET = """Techniques=vort_MotionEffects@vort_Motion.fx,DLSS5_Feed@DLSS5_Feed.fx
TechniqueSorting=vort_MotionEffects@vort_Motion.fx,DLSS5_Feed@DLSS5_Feed.fx
"""
FEED_CFG = """enabled=1
mode=2
hdr=-1
depth_inverted=-1
flags=-1
reset_every=0
warmup_rebuild=180
rebuild=0
log_frames=3
create_delay=60
preset=6
mv_scale_x=1.000
mv_scale_y=1.000
"""


class StackError(Exception):
    pass


# ---------------------------------------------------------------- helpers
def say(log, text):
    if log:
        log(text)
    else:
        print(text, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, log=None, label=None):
    """Download url to dest, resuming nothing, reporting progress in MB."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    label = label or os.path.basename(dest)
    req = urllib.request.Request(url, headers={"User-Agent": "neural-lens-stack/" + __version__})
    last = [0.0]
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(dest + ".part", "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if time.perf_counter() - last[0] > 1.0:
                        last[0] = time.perf_counter()
                        if total:
                            say(log, "    %s  %d of %d MB" % (label, done >> 20, total >> 20))
                        else:
                            say(log, "    %s  %d MB" % (label, done >> 20))
            os.replace(dest + ".part", dest)
            return dest
        except Exception as exc:
            if attempt == 2:
                raise StackError("could not download %s: %s" % (url, exc))
            say(log, "    retrying %s (%s)" % (label, exc))
            time.sleep(2)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "neural-lens-stack/" + __version__,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def feeder_hash_in_notes(notes, asset_name):
    """The SHA-256 the Feed's release notes print for this zip, or None."""
    m = re.search(r"SHA-256 of `?%s`?\s*:\s*`?([0-9A-Fa-f]{64})" % re.escape(asset_name), notes or "")
    return m.group(1).lower() if m else None


def verify_feeder_zip(path, asset_name, notes):
    """Refuse a Feed zip unless its hash is the one its release notes print, or
    one this file knows. Fake copies of the Feed are circulating, so a zip that
    matches neither is removed and named, not installed."""
    got = sha256(path).lower()
    want = feeder_hash_in_notes(notes, asset_name)
    if got == want or got in HASHES.get("dlss5-feeder.zip", []):
        return path
    try:
        os.remove(path)
    except OSError:
        pass
    if want is None:
        raise StackError("%s was not installed. Its release notes print no SHA-256 for it, and its hash "
                         "is not one this program knows.\n  got  %s\nThe lens's next release will carry the "
                         "hash once the zip is verified." % (asset_name, got))
    raise StackError("%s was not installed. It does not match the SHA-256 its release notes print.\n"
                     "  got    %s\n  notes  %s\nEither the download was tampered with or the release was "
                     "replaced. Nothing was changed." % (asset_name, got, want))


def check_hash(path, want, label):
    """Refuse a file whose hash is not one of the known ones, and remove it."""
    got = sha256(path)
    if got not in want:
        try:
            os.remove(path)
        except OSError:
            pass
        raise StackError("%s matches no known hash\n  got      %s\n  known    %s\nNot installed. The "
                         "project may have replaced the file; the lens's release notes will say when a "
                         "new one is verified." % (label, got, ", ".join(want)))
    return path


def set_ini_values(text, values):
    """Set each key = value line of an ini's text, wherever the key is, and keep
    everything else as it was, comments included."""
    for key, value in values.items():
        text, n = re.subn(r"(?im)^([ \t]*%s[ \t]*=)[^\r\n]*" % re.escape(key),
                          lambda m: m.group(1) + " " + value, text)
        if not n:
            raise StackError("the Cost Scaler's ini has no %s setting" % key)
    return text


def gpu_supported():
    """(True, capability) when Neural Rendering can run here, else (False, why).

    The SF-v2 build serves every generation, so the question is whether this is
    an RTX card at all, and the capability then says whether it gets NVIDIA's
    package as well, see gets_package. Compute capability 7.5 is Turing, the
    first RTX line and where Neural Rendering starts; a machine with no
    nvidia-smi has no NVIDIA driver. Capability is steadier than marketing
    names, which fragment into "RTX 4090 Laptop GPU" and "RTX 4000 Ada
    Generation".
    """
    smi = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    if not os.path.isfile(smi):
        smi = "nvidia-smi"
    try:
        # no console window for the child: without this the first console
        # program started while a shown topmost Tk window is up took 5 seconds
        # under pythonw and the frozen exe, which showed as a blank setup window
        out = subprocess.run([smi, "--query-gpu=compute_cap", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20,
                             stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).stdout
    except Exception:
        return False, "no NVIDIA driver here (nvidia-smi would not run)"
    caps = [c.strip() for c in out.splitlines() if c.strip()]
    if not caps:
        return False, "the driver reported no compute capability"
    try:
        cap = float(caps[0])
    except ValueError:
        return False, "the driver reported %r, which is not a capability" % caps[0]
    if cap < 7.5:
        return False, ("compute capability %s is older than the RTX 20 series, and "
                       "Neural Rendering needs the tensor cores an RTX card has" % caps[0])
    return True, caps[0]


def gets_package(capability):
    """Whether a card of this compute capability, as gpu_supported gives it, gets
    NVIDIA's package for its model, see NVIDIA_PACKAGE."""
    try:
        return float(capability) >= NVIDIA_FROM_CAPABILITY
    except (TypeError, ValueError):
        return False


def download_mb(capability=None):
    """What the download comes to on this card, see DOWNLOAD_MB, asking the card
    where no capability is given."""
    if capability is None:
        ok, capability = gpu_supported()
        if not ok:
            return DOWNLOAD_MB
    return DOWNLOAD_MB_PACKAGE if gets_package(capability) else DOWNLOAD_MB


def model_in(target):
    """Which model the stack folder holds as nvngx_dlssnr_real.dll: NVIDIA_MODEL,
    with the large and the small FP8 networks, MODEL, which stands for any
    other build, each of which holds the large network alone, or None where
    there is no model. Told by the file's size, since every model the setup
    installs passed its hash check first. The lens asks this to know whether its
    Model setting has two networks to choose from."""
    try:
        size = os.path.getsize(os.path.join(target, "nvngx_dlssnr_real.dll"))
    except (OSError, TypeError):
        return None
    return NVIDIA_MODEL if size == NVIDIA_PACKAGE["model_size"] else MODEL


def model_line(target):
    """The self test's line on the model in the stack folder, see model_in."""
    model = model_in(target)
    if model is None:
        return "    model: none, there is no nvngx_dlssnr_real.dll"
    if model == NVIDIA_MODEL:
        return "    model: NVIDIA's %s, with %s and %s" % (NVIDIA_MODEL, LARGE_SAID, SMALL_SAID)
    return "    model: %s, with %s alone" % (MODEL, LARGE_SAID)


# ---------------------------------------------------------------- NVIDIA's package, a 7z archive
# NVIDIA's package is a 7z archive, and the standard library reads no 7z. What
# it holds is LZMA2 in one block a file, which the standard library's lzma
# decodes, so this reads that much of the format and no more: the start header,
# the header, packed with LZMA as 7-Zip writes it or not, and a folder of one
# LZMA2 or LZMA coder for each file. Anything else, a filter, a solid block, a
# password, is refused, and the setup then takes the model through the RHI
# manifest, see Install.step_nvidia. Nothing in the archive is run: the two
# files taken out are bytes written to a file, the model checked by its hash
# and the archive by its own CRCs. The layout is 7-Zip's 7zFormat.txt.
SEVENZIP_SIGNATURE = b"7z\xbc\xaf\x27\x1c"
_LZMA2, _LZMA1 = b"\x21", b"\x03\x01\x01"


class _Header:
    """The bytes of a 7z header, read in its own types."""

    def __init__(self, data):
        self.b, self.at = data, 0

    def byte(self):
        if self.at >= len(self.b):
            raise StackError("its header ends early")
        v = self.b[self.at]
        self.at += 1
        return v

    def take(self, n):
        if self.at + n > len(self.b):
            raise StackError("its header ends early")
        v = self.b[self.at:self.at + n]
        self.at += n
        return v

    def number(self):
        """7z's number: the first byte's high bits say how many bytes follow."""
        first, mask, value = self.byte(), 0x80, 0
        for i in range(8):
            if not first & mask:
                return value | ((first & (mask - 1)) << (8 * i))
            value |= self.byte() << (8 * i)
            mask >>= 1
        return value

    def bits(self, n):
        out, mask, cur = [], 0, 0
        for _ in range(n):
            if not mask:
                cur, mask = self.byte(), 0x80
            out.append(bool(cur & mask))
            mask >>= 1
        return out

    def digests(self, n):
        defined = [True] * n if self.byte() else self.bits(n)
        return [struct.unpack("<I", self.take(4))[0] if d else None for d in defined]


def _7z_streams(h):
    """A streams info: where the packed streams start and their sizes, the
    folders, their unpacked sizes and CRCs, and how a folder splits into files."""
    info = {"pack_pos": 0, "pack_sizes": [], "folders": [], "unpack": [], "crcs": [], "sub": None}
    while True:
        kind = h.number()
        if kind == 0x00:
            return info
        if kind == 0x06:                    # the packed streams
            info["pack_pos"] = h.number()
            n = h.number()
            while True:
                k = h.number()
                if k == 0x00:
                    break
                if k == 0x09:
                    info["pack_sizes"] = [h.number() for _ in range(n)]
                elif k == 0x0A:
                    h.digests(n)
                else:
                    raise StackError("its packed streams have a property %d" % k)
        elif kind == 0x07:                  # the folders
            if h.number() != 0x0B:
                raise StackError("it lists no folders")
            n = h.number()
            if h.byte():
                raise StackError("its folders are kept outside the header")
            for _ in range(n):
                info["folders"].append(_7z_folder(h))
            if h.number() != 0x0C:
                raise StackError("its folders have no sizes")
            info["unpack"] = [[h.number() for _ in range(f["outs"])] for f in info["folders"]]
            while True:
                k = h.number()
                if k == 0x00:
                    break
                if k == 0x0A:
                    info["crcs"] = h.digests(n)
                else:
                    raise StackError("its folders have a property %d" % k)
        elif kind == 0x08:                  # the files in each folder
            info["sub"] = _7z_files_in_folders(h, info)
        else:
            raise StackError("its streams have a property %d" % kind)


def _7z_folder(h):
    coders, ins, outs = [], 0, 0
    for _ in range(h.number()):
        flags = h.byte()
        if flags & 0xC0:
            raise StackError("a coder of a kind this setup does not read")
        codec = h.take(flags & 0x0F)
        n_in, n_out = (h.number(), h.number()) if flags & 0x10 else (1, 1)
        props = h.take(h.number()) if flags & 0x20 else b""
        coders.append((codec, props))
        ins, outs = ins + n_in, outs + n_out
    for _ in range(outs - 1):              # how the coders are bound together
        h.number(), h.number()
    packed = ins - (outs - 1)
    if packed > 1:
        for _ in range(packed):
            h.number()
    return {"coders": coders, "ins": ins, "outs": outs, "packed": packed}


def _7z_files_in_folders(h, info):
    counts = [1] * len(info["folders"])
    crcs = []
    k = h.number()
    if k == 0x0D:
        counts = [h.number() for _ in info["folders"]]
        k = h.number()
    if k == 0x09:
        for c in counts:
            for _ in range(max(0, c - 1)):
                h.number()
        k = h.number()
    unknown = sum(c for i, c in enumerate(counts)
                  if not (c == 1 and i < len(info["crcs"]) and info["crcs"][i] is not None))
    while k != 0x00:
        if k != 0x0A:
            raise StackError("its files have a property %d" % k)
        crcs = h.digests(unknown)
        k = h.number()
    return {"counts": counts, "crcs": crcs}


def _7z_filters(codec, props):
    """The lzma filter chain that decodes a coder, LZMA2 or LZMA, refusing any other."""
    if codec == _LZMA2 and len(props) == 1 and props[0] <= 40:
        bits = props[0]
        size = 0xFFFFFFFF if bits == 40 else (2 | (bits & 1)) << (bits // 2 + 11)
        return [{"id": lzma.FILTER_LZMA2, "dict_size": size}]
    if codec == _LZMA1 and len(props) == 5:
        d = props[0]
        return [{"id": lzma.FILTER_LZMA1, "dict_size": struct.unpack("<I", props[1:])[0],
                 "lc": d % 9, "lp": (d // 9) % 5, "pb": d // 45}]
    raise StackError("a coder this setup does not read, %s" % codec.hex())


def _7z_unpack(f, offset, packed, folder, size, sink):
    """Decode a folder of one coder from the open archive f, packed bytes from
    offset, into size bytes, handing each piece to sink as it comes."""
    if len(folder["coders"]) != 1 or folder["packed"] != 1:
        raise StackError("a folder of %d coders" % len(folder["coders"]))
    d = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=_7z_filters(*folder["coders"][0]))
    f.seek(offset)
    left, done = packed, 0
    try:
        while done < size:
            chunk = b""
            if d.needs_input:
                if not left:
                    raise StackError("its packed data ends early")
                chunk = f.read(min(left, 1 << 20))
                if not chunk:
                    raise StackError("the file ends early")
                left -= len(chunk)
            out = d.decompress(chunk, max_length=min(1 << 22, size - done))
            if out:
                sink(out)
                done += len(out)
            elif d.eof:
                break
    except lzma.LZMAError as exc:
        raise StackError("its data does not decode, %s" % exc)
    if done != size:
        raise StackError("a file gave %d bytes where the archive says %d" % (done, size))


def read_7z(path):
    """The files of a 7z archive that hold data, in order, each a dict of its
    name with forward slashes, where its packed data is, its folder, its size
    and its CRC. StackError where the archive is not one this setup reads."""
    with open(path, "rb") as f:
        start = f.read(32)
        if len(start) != 32 or start[:6] != SEVENZIP_SIGNATURE:
            raise StackError("it is not a 7z archive")
        if zlib.crc32(start[12:32]) != struct.unpack("<I", start[8:12])[0]:
            raise StackError("its start header is damaged")
        offset, size, crc = struct.unpack("<QQI", start[12:32])
        f.seek(32 + offset)
        data = f.read(size)
        if len(data) != size or zlib.crc32(data) != crc:
            raise StackError("its header is damaged or cut short")
        h = _Header(data)
        kind = h.number()
        if kind == 0x17:                    # the header packed, as 7-Zip writes it
            info = _7z_streams(h)
            if not info["folders"] or not info["pack_sizes"]:
                raise StackError("its packed header has nothing in it")
            out = []
            _7z_unpack(f, 32 + info["pack_pos"], info["pack_sizes"][0], info["folders"][0],
                       info["unpack"][0][-1], out.append)
            data = b"".join(out)
            if info["crcs"] and info["crcs"][0] is not None and zlib.crc32(data) != info["crcs"][0]:
                raise StackError("its packed header is damaged")
            h = _Header(data)
            kind = h.number()
        if kind != 0x01:
            raise StackError("it has no header")
        main, names, empty = None, [], []
        while True:
            k = h.number()
            if k == 0x00:
                break
            if k == 0x04:
                main = _7z_streams(h)
            elif k == 0x05:
                n = h.number()
                while True:
                    p = h.number()
                    if p == 0x00:
                        break
                    body = _Header(h.take(h.number()))
                    if p == 0x0E:
                        empty = body.bits(n)
                    elif p == 0x11:
                        if body.byte():
                            raise StackError("its names are kept outside the header")
                        names = body.take(len(body.b) - 1).decode("utf-16-le").split("\0")[:n]
            else:
                raise StackError("its header has a property %d" % k)
    if main is None:
        return []
    with_data = [name for name, e in zip(names, empty or [False] * len(names)) if not e]
    sub = main["sub"] or {"counts": [1] * len(main["folders"]), "crcs": []}
    crcs, at, out = list(sub["crcs"]), 32 + main["pack_pos"], []
    if len(with_data) != len(main["folders"]) or len(main["pack_sizes"]) != len(main["folders"]):
        raise StackError("it has %d files with data in %d folders" % (len(with_data), len(main["folders"])))
    for i, folder in enumerate(main["folders"]):
        if sub["counts"][i] != 1:
            raise StackError("it holds a solid block of %d files" % sub["counts"][i])
        crc = main["crcs"][i] if i < len(main["crcs"]) else None
        if crc is None and crcs:
            crc = crcs.pop(0)
        out.append({"name": with_data[i].replace("\\", "/"), "offset": at, "packed": main["pack_sizes"][i],
                    "folder": folder, "size": main["unpack"][i][-1], "crc": crc})
        at += main["pack_sizes"][i]
    return out


def extract_7z(path, name, dest):
    """Write the file of the archive named so, forward slashes and any case, to
    dest, checked against its CRC. Returns its size and its sha256."""
    for e in read_7z(path):
        if e["name"].lower() != name.lower():
            continue
        digest, crc = hashlib.sha256(), [0]
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(path, "rb") as f, open(dest, "wb") as out:
            def sink(piece):
                out.write(piece)
                digest.update(piece)
                crc[0] = zlib.crc32(piece, crc[0])
            _7z_unpack(f, e["offset"], e["packed"], e["folder"], e["size"], sink)
        if e["crc"] is not None and crc[0] != e["crc"]:
            raise StackError("%s in it does not match its CRC" % name)
        return e["size"], digest.hexdigest()
    raise StackError("it holds no %s" % name)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    return path


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def presenter_command(target):
    """How to start the presenter in a stack folder: the program itself when
    installed, and from source the interpreter's copy, which has a pyvenv.cfg
    beside it, with the script."""
    exe = os.path.join(target, "lens-presenter.exe")
    if FROZEN or not os.path.isfile(os.path.join(target, "pyvenv.cfg")):
        return [exe]
    return [exe, os.path.join(APP_DIR, "lens_presenter.py")]


def fast_engine_dirs(target):
    """The folders a lens with this stack folder looks in for the fast engine,
    lens-fast.exe, in the order neural_lens.py's _find_fast_exe looks: the
    stack's fast folder, where an install has it, then from source the folder
    fast_engine\\build.cmd builds it into. The engine writes its own copy of
    the proxy's ini beside its exe."""
    dirs = [os.path.join(target, "fast")]
    if not FROZEN:
        dirs.append(os.path.join(APP_DIR, "fast_engine", "bin"))
    return dirs


def fast_engine_line(target):
    """One line for the setup's summary and its check that says whether the
    fast engine is there. Without it a fullscreen lens runs on the presenter,
    the ReShade engine, as a windowed lens does."""
    for d in fast_engine_dirs(target):
        exe = os.path.join(d, "lens-fast.exe")
        if os.path.isfile(exe):
            return "    fast engine: found, %s" % exe
    if FROZEN:
        line = ("    fast engine: not found in %s, so a fullscreen lens uses the ReShade engine."
                % os.path.join(target, "fast"))
        # the installer puts it in the program's folder only, so a reinstall mends
        # only the stack that is that folder
        if same_path(target, APP_DIR):
            line += " Installing the lens again puts it back."
        return line
    return ("    fast engine: not built, so a fullscreen lens uses the ReShade engine, as a windowed "
            "lens does. fast_engine\\build.cmd builds it. It needs Visual Studio 2022 or later, or "
            "its Build Tools, with the workload \"Desktop development with C++\" and Windows SDK "
            "10.0.26100 or later.")


# ---------------------------------------------------------------- the Home menu add-on
def addon_build_named(value):
    """The build a word names: 8.5 for 8.5, 8.5.0-rc10 or rc10, whatever its
    case, and 5.2.1, the default, for anything else, nothing included."""
    word = str(value or "").strip().strip('"').lower()
    return "8.5" if word in ("8.5", "8.5.0-rc10", "rc10") else ADDON_DEFAULT


def addon_choice(ini=None):
    """The build the lens has chosen for the Home menu add-on, addon in its
    neural-lens.ini, see addon_build_named. The ini is the one the lens reads,
    the file NEURAL_LENS_INI names or neural-lens.ini beside this file, so the
    installer's run of the setup, the Start Menu's and a repair all keep the
    lens's choice. A key given twice counts at its last line, as the lens
    reads it."""
    path = ini or os.environ.get("NEURAL_LENS_INI") or os.path.join(APP_DIR, "neural-lens.ini")
    word = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                bare = line.strip()
                if bare and bare[0] not in "#;[" and "=" in bare:
                    key, value = bare.split("=", 1)
                    if key.strip().lower() == "addon":
                        word = value
    except OSError:
        pass
    return addon_build_named(word)


def addon_words(build):
    """A build as the setup's lines name it: its version, or what it is."""
    if build in ADDON_BUILDS:
        return ADDON_BUILDS[build]["version"]
    return "a build this setup does not know" if build == "other" else "none"


_IN_PLACE = {}


def addon_in_place(target):
    """Which build the add-on in the stack folder is, by its hash: 5.2.1, 8.5,
    other for a file that is neither, or None where there is none. The answer
    is kept for the file's size and time, so asking again before every
    presenter start costs nothing while the file stays as it is."""
    path = os.path.join(target, "renodx-dlss5.addon64")
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)
    if key not in _IN_PLACE:
        try:
            got = sha256(path)
        except OSError:
            return "other"
        _IN_PLACE[key] = next((b for b, d in ADDON_BUILDS.items() if got in d["addon"]), "other")
    return _IN_PLACE[key]


def addon_zip_path(target, build):
    """Where the build's zip is kept: in ADDON_DIR in the stack folder, under
    the name its release gives it."""
    return os.path.join(target, ADDON_DIR, "renodx-dlss5_%s.zip" % ADDON_BUILDS[build]["version"])


def addon_zip(target, build, log=None, fetch_missing=True):
    """The build's zip in the stack's addons folder, checked by its hash. One
    that is missing, or does not check out, is fetched from its release on
    the RHI repository with fetch_missing, and is None without it. A download
    that matches no known hash is removed and refused, see check_hash."""
    d = ADDON_BUILDS[build]
    path = addon_zip_path(target, build)
    try:
        if sha256(path) in d["zip"]:
            return path
    except OSError:
        pass
    if not fetch_missing:
        return None
    fetch(d["url"], path, log, "RenoDX DLSS 5 " + d["version"])
    return check_hash(path, d["zip"], os.path.basename(path))


def addon_file(zip_path, build):
    """The add-on in the build's zip, as bytes, checked by its hash."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith(".addon64")), None)
            data = zf.read(member) if member else None
    except (OSError, zipfile.BadZipFile) as exc:
        raise StackError("the RenoDX archive %s could not be read: %s" % (zip_path, exc))
    if data is None:
        raise StackError("the RenoDX archive holds no add-on")
    got = hashlib.sha256(data).hexdigest()
    if got not in ADDON_BUILDS[build]["addon"]:
        raise StackError("the RenoDX DLSS 5 add-on %s matches no known hash\n  got      %s\n  known    %s\n"
                         "Not installed." % (ADDON_BUILDS[build]["version"], got,
                                             ", ".join(ADDON_BUILDS[build]["addon"])))
    return data


def section_values(lines):
    """The key=value lines of a section, [(key, value)] in their order, with
    blank lines and comments left out, and a key given twice where it first
    stood, at its last value."""
    out, at = [], {}
    for line in lines or ():
        bare = line.strip()
        if not bare or bare[0] in "#;[" or "=" not in bare:
            continue
        key, value = bare.split("=", 1)
        key, value = key.strip(), value.strip()
        if key.lower() in at:
            out[at[key.lower()]] = (out[at[key.lower()]][0], value)
        else:
            at[key.lower()] = len(out)
            out.append((key, value))
    return out


def section_build(values):
    """The build a section was written for, by its ConfigVersion: the build
    whose schema it is, or None for any other or none."""
    v = next((v for k, v in values or () if k.lower() == "configversion"), None)
    return next((b for b, d in ADDON_BUILDS.items() if v is not None and v.strip() == d["schema"]), None)


def _number(text):
    try:
        v = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _on(text):
    """A switch of the section as the add-ons read one: on for true, yes, on
    or a number other than 0."""
    word = str(text).strip().lower()
    return word in ("true", "yes", "on") or _number(word) not in (None, 0.0)


def _carried(key, value, dst, kept):
    """A value of ADDON_SHARED as it goes to the build dst, see there, or None
    where it stays out. kept is dst's own copy, by its keys in lower case."""
    if key == "NRSkinStructure":
        n, had = _number(value), _number(kept.get("nrskinstructure"))
        if dst == "8.5" and n is not None and n > 1:
            return "1"
        if dst == "5.2.1" and n == 1 and had is not None and had > 1:
            return kept["nrskinstructure"]
    if key == "NRCodecMode" and dst == "5.2.1" and value.strip() not in ("0", "1"):
        return kept.get("nrcodecmode")
    return value


def section_convert(values, src, dst, base=None):
    """The add-on's section, values as section_values gives them, written for
    the build src, as the build dst reads it. ConfigVersion comes first, at
    dst's schema, then each key of base, dst's own copy of the section or the
    section dst has now, that only dst reads, then each key of ADDON_SHARED
    the section has, with its value, and before upscaling under dst's name,
    see ADDON_HOOK. A key of ADDON_SHARED the section lacks stays out, so dst
    runs its default for it as src did, and a key only src reads stays behind,
    in src's own copy. Skin structure and the codec go as ADDON_SHARED says.
    The keys stand in base's order where base has them, and the rest after
    them, so a round trip gives a section back as it was, line for line. With
    src and dst the same, the section comes back at dst's schema."""
    schema = ADDON_BUILDS[dst]["schema"]
    if src == dst:
        return [("ConfigVersion", schema)] + [(k, v) for k, v in values if k.lower() != "configversion"]
    shared = {k.lower(): k for k in ADDON_SHARED}
    hooks = {k.lower() for k in ADDON_HOOK.values()}
    kept = {k.lower(): v for k, v in base or ()}
    got = {}                                    # by the key in lower case, (key, value), in the order found
    for k, v in base or ():
        if k.lower() != "configversion" and k.lower() not in shared and k.lower() not in hooks:
            got.setdefault(k.lower(), (k, v))
    for k, v in values:
        if k.lower() in shared and k.lower() not in got:
            v = _carried(shared[k.lower()], v, dst, kept)
            if v is not None:
                got[k.lower()] = (shared[k.lower()], v)
    have = {k.lower(): v for k, v in values}
    hook = None
    if src == "8.5" and "nrhookpoint" in have:
        hook = "1" if _number(have["nrhookpoint"]) == 1 else "0"
    elif "nrpreupscale" in have:
        hook = "1" if _on(have["nrpreupscale"]) else "0"
    if hook is not None:
        got[ADDON_HOOK[dst].lower()] = (ADDON_HOOK[dst], hook)
    order = [k.lower() for k, _v in base or () if k.lower() in got]
    order += [k for k in got if k not in order]
    return [("ConfigVersion", schema)] + [got[k] for k in dict.fromkeys(order)]


def ini_section(path, name=ADDON_SECTION):
    """A section of an ini, by default the add-on's of ReShade.ini, as
    section_values gives it, or None where the file has no such section or
    cannot be read. The section is found by its name whatever its case, and a
    name given twice counts at each."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    want, inside, found, body = name.strip("[]").strip().lower(), False, False, []
    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            title = bare[1:bare.index("]")] if "]" in bare else bare[1:]
            inside = title.strip().lower() == want
            found = found or inside
        elif inside:
            body.append(line)
    return section_values(body) if found else None


def ini_put_section(path, values, name=ADDON_SECTION):
    """Make a section of an ini, by default the add-on's of ReShade.ini, hold
    these values, key=value lines in their order, and nothing else, and leave
    every other line of the file as it is, with the file's own line ends. A
    second section of the name goes, and a file without one gets it at its
    end, as a file that is not there yet gets it alone. The file is written
    beside itself and put in its place in one step, so a reader never finds it
    cut short."""
    try:
        with open(path, "rb") as f:
            lines = f.read().decode("utf-8", "surrogateescape").splitlines(True)
    except FileNotFoundError:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        lines = []
    eol = "\r\n" if not lines or any(line.endswith("\r\n") for line in lines) else "\n"
    want = name.strip("[]").strip().lower()
    body = ["%s=%s%s" % (k, v, eol) for k, v in values]
    out, inside, done = [], False, False
    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside and done and out and out[-1].strip():
                out.append(eol)                 # a blank line before the next section
            title = bare[1:bare.index("]")] if "]" in bare else bare[1:]
            inside = title.strip().lower() == want
            if inside and done:
                continue                        # a second section of the name goes
            out.append(line if line.endswith(("\n", "\r")) else line + eol)
            if inside:
                out.extend(body)
                done = True
        elif not inside:
            out.append(line)
    if not done:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += eol
        out.append("%s%s%s" % (eol if out and out[-1].strip() else "", name, eol))
        out.extend(body)
    with open(path + ".tmp", "wb") as f:
        f.write("".join(out).encode("utf-8", "surrogateescape"))
    os.replace(path + ".tmp", path)


def addon_kept_path(target, build):
    """Where the build's own copy of the add-on's section is kept."""
    return os.path.join(target, ADDON_DIR, "section-%s.ini" % build)


def addon_kept(target, build):
    """The build's own copy of the add-on's section, as section_values gives
    it, or None where it has none yet."""
    return ini_section(addon_kept_path(target, build))


def addon_keep(target, build, values):
    """Keep these values as the build's own copy of the add-on's section, the
    section as the build last had it, for the next switch to it."""
    path = addon_kept_path(target, build)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8", newline="") as f:
        f.write("%s\r\n" % ADDON_SECTION + "".join("%s=%s\r\n" % kv for kv in values))
    os.replace(path + ".tmp", path)
    return path


def addon_switch(target, build, log=None, fetch_missing=False):
    """Make the stack run this build of the Home menu add-on: its add-on in
    place as renodx-dlss5.addon64, and the add-on's section of ReShade.ini in
    its schema. For a stack whose ReShade engine is not running, since the
    presenter holds the add-on it loaded and reads the section only as it
    starts. The section as it was is kept as the copy of the build it was
    written for, and the build that comes reads the values both builds read
    from it, and the rest from its own copy, see section_convert. The add-on
    comes out of the zip in ADDON_DIR, fetched first with fetch_missing, and
    nothing changes until it checks out. Should the add-on not go in place,
    the section goes back as it was. A stack whose add-on is neither build is
    left alone, and says so, and one with no add-on at all is the stack
    setup's to mend. Returns whether anything changed."""
    if build not in ADDON_BUILDS:
        raise StackError("there is no build %s of the add-on" % build)
    have = addon_in_place(target)
    if have is None:
        return False
    if have == "other":
        raise StackError("the add-on in %s is neither build the lens knows, so it is left as it is" % target)
    ini = os.path.join(target, "ReShade.ini")
    now = ini_section(ini)
    src = section_build(now) or have or build
    data = None
    if have != build:
        z = addon_zip(target, build, log, fetch_missing)
        if z is None:
            raise StackError("the %s add-on is not in %s yet" % (ADDON_BUILDS[build]["version"],
                                                                  os.path.join(target, ADDON_DIR)))
        data = addon_file(z, build)
    convert = now is not None and src != build
    if data is None and not convert:
        return False
    if convert:
        addon_keep(target, src, now)
        ini_put_section(ini, section_convert(now, src, build, addon_kept(target, build)))
    if data is not None:
        dest = os.path.join(target, "renodx-dlss5.addon64")
        try:
            write_bytes(dest + ".part", data)
            os.replace(dest + ".part", dest)
        except OSError as exc:
            if convert:
                ini_put_section(ini, now)
            raise StackError("the %s add-on could not be put in place in %s: %s"
                             % (ADDON_BUILDS[build]["version"], target, exc))
    say(log, "the Home menu add-on is %s%s" % (ADDON_BUILDS[build]["version"], (
        ", with the add-on's section of ReShade.ini carried over from %s" % ADDON_BUILDS[src]["version"])
        if convert else ""))
    return True


def addon_backups(target):
    """The copies of ReShade.ini the 8.5 build makes beside it, each before it
    migrates a section written for another schema, see ADDON_SECTION."""
    try:
        return sorted(os.path.join(target, f) for f in os.listdir(target)
                      if f.startswith(ADDON_BACKUP) and f.endswith(".bak"))
    except OSError:
        return []


def addon_journal_trim(target, most=ADDON_JOURNAL_MOST):
    """Cut the 8.5 build's journal, ADDON_JOURNAL beside the presenter, back to
    its newest lines once it has grown past most bytes. The build adds a few
    lines at every presenter start, the session and how it ended, and never
    cuts the file itself, so in the lens, which starts its presenter often, it
    would grow for good. What stays is the last half of most, from the first
    line in it that starts a session. Returns how many bytes stay, or None
    where the file was left as it was."""
    path = os.path.join(target, ADDON_JOURNAL)
    try:
        if os.path.getsize(path) <= most:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    tail = data[-(most // 2):]
    start = tail.find(b"\n[session]")
    if start < 0:
        start = tail.find(b"\n")
    tail = tail[start + 1:] if start >= 0 else b""
    try:
        with open(path + ".tmp", "wb") as f:
            f.write(tail)
        os.replace(path + ".tmp", path)
    except OSError:
        try:
            os.remove(path + ".tmp")
        except OSError:
            pass
        return None
    return len(tail)


# ---------------------------------------------------------------- steps
class Install:
    def __init__(self, target=DEFAULT_TARGET, dlssnr=None, dlss=None, log=None, provider="drme"):
        self.target = os.path.abspath(target)
        self.given = {"nvngx_dlssnr.dll": dlssnr, "nvngx_dlss.dll": dlss}
        self.log = log
        self.provider = provider if provider in PROVIDERS else "drme"
        self.record = {"version": __version__, "target": self.target, "layer_dir": LAYER_DIR,
                       "files": [], "registry": [], "components": {}}
        # the record an earlier run left in the folder, which says whether the
        # model's preset was set already, see step_config
        self.earlier = {}

    def say(self, text):
        say(self.log, text)

    def add(self, path):
        path = os.path.abspath(path)
        if path not in self.record["files"]:
            self.record["files"].append(path)
        return path

    def run(self):
        if FROZEN and not same_path(self.target, APP_DIR):
            raise StackError("the installed lens keeps its stack in its own folder, %s, beside "
                             "lens-presenter.exe; --target is for running from source" % APP_DIR)
        try:
            with open(os.path.join(self.target, "install-record.json"), encoding="utf-8") as f:
                self.earlier = json.load(f)
        except (OSError, ValueError):
            self.earlier = {}
        if not isinstance(self.earlier, dict):
            self.earlier = {}
        self.retire_old_stack()
        os.makedirs(self.target, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.say("Installing the Neural Rendering stack into %s" % self.target)
        self.step_presenter()
        self.step_reshade()
        self.step_nvidia()
        self.step_cost_scaler()
        self.step_feeder()
        self.step_renodx()
        self.step_shaders()
        self.step_config()
        self.step_layer()
        self.write_record()
        self.say("")
        self.say("Installed. Running the self test.")
        ok, detail = verify(self.target, log=self.log)
        self.say(detail)
        self.say(layer_line(layer_ungated()))
        self.say(fast_engine_line(self.target))
        if ok:
            # the downloads served their purpose; a failed run keeps them so a
            # retry can be looked into with them still there
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
        return ok

    def retire_old_stack(self):
        """Take out a stack that 0.1.0 assembled, which held mpv.

        Installed, 0.1.0 kept its stack in APP\\stack; from source it used the
        same stack folder this installs into. Its record lists what it wrote.
        NVIDIA's two runtimes and ReShade's DLL are kept where this install
        wants them when they check out, so they are not downloaded again, and
        the rest goes the way the record's uninstall takes it, the layer
        registration and the allow list that named mpv included. Installed,
        whatever is still in APP\\stack after that goes too: the folder
        belonged to the setup.
        """
        old = os.path.join(APP_DIR, "stack") if FROZEN else self.target
        try:
            with open(os.path.join(old, "install-record.json"), encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError):
            return
        if "mpv" not in record.get("components", {}):
            return
        self.say("Removing the stack an earlier version assembled, which held mpv")
        os.makedirs(self.target, exist_ok=True)
        model = HASHES["nvngx_dlssnr.dll"][MODEL] + HASHES["nvngx_dlssnr.dll"][NVIDIA_MODEL]
        moves = (("nvngx_dlss.dll", "nvngx_dlss.dll", HASHES["nvngx_dlss.dll"]),
                 ("nvngx_dlssnr_real.dll", "nvngx_dlssnr_real.dll", model),
                 ("nvngx_dlssnr.dll", "nvngx_dlssnr_real.dll", model))
        keep = []
        for name, dest_name, want in moves:
            src, dest = os.path.join(old, name), os.path.join(self.target, dest_name)
            try:
                if not os.path.isfile(src) or sha256(src) not in want:
                    continue
                if same_path(src, dest):
                    keep.append(dest)
                elif not os.path.isfile(dest):
                    os.replace(src, dest)
                    keep.append(dest)
                else:
                    continue
                self.say("    kept %s" % dest_name)
            except OSError:
                pass
        if record.get("components", {}).get("reshade") == RESHADE_VERSION:
            keep.append(os.path.join(LAYER_DIR, "ReShade64.dll"))
        uninstall(old, log=self.log, keep=keep)
        if FROZEN:
            shutil.rmtree(old, ignore_errors=True)

    # the presenter, in the stack folder beside the ReShade.ini that ReShade looks for
    def step_presenter(self):
        """Installed, lens-presenter.exe is part of the program and already in
        its folder, which is the stack folder. From source it is a copy of the
        Python running this, which runs lens_presenter.py beside this file: a
        pyvenv.cfg beside the copy points it at this Python's library, and a
        .pth file at the packages this Python sees, a virtual environment's
        included. Its packages are checked first, before anything is downloaded.
        """
        exe = os.path.join(self.target, "lens-presenter.exe")
        if FROZEN:
            if not os.path.isfile(exe):
                raise StackError("lens-presenter.exe is missing from %s; reinstall the lens" % self.target)
            self.say("presenter: lens-presenter.exe, part of the lens")
            return
        import importlib.util
        import site
        need = {"glfw": "glfw", "vulkan": "vulkan", "numpy": "numpy", "windows_capture": "windows-capture"}
        missing = [pip for mod, pip in need.items() if importlib.util.find_spec(mod) is None]
        if missing:
            raise StackError("the presenter needs %s for this Python first:\n  pip install %s"
                             % (", ".join(missing), " ".join(missing)))
        base = os.path.dirname(getattr(sys, "_base_executable", None) or sys.executable)
        python = os.path.join(base, "python.exe")
        if not os.path.isfile(python):
            raise StackError("there is no python.exe beside %s to copy as the presenter" % base)
        shutil.copy2(python, exe)
        self.add(exe)
        self.add(write_text(os.path.join(self.target, "pyvenv.cfg"),
                            "home = %s\ninclude-system-site-packages = true\nversion = %d.%d\n"
                            % (base, sys.version_info[0], sys.version_info[1])))
        paths = [p for p in site.getsitepackages() + [site.getusersitepackages()] if os.path.isdir(p)]
        self.add(write_text(os.path.join(self.target, "Lib", "site-packages", "lens-presenter.pth"),
                            "\n".join(paths) + "\n"))
        self.say("presenter: a copy of %s, running lens_presenter.py" % python)

    # ReShade: the DLL is read straight out of the setup exe, which is a zip, so
    # nothing of ReShade's is executed here. The layer manifest is written below.
    def step_reshade(self):
        dll = os.path.join(LAYER_DIR, "ReShade64.dll")
        if os.path.isfile(dll):
            self.say("ReShade: layer already present, keeping it")
        else:
            setup = fetch(SOURCES["reshade"], os.path.join(CACHE_DIR, "ReShade_Setup_%s_Addon.exe" % RESHADE_VERSION),
                          self.log, "ReShade " + RESHADE_VERSION)
            os.makedirs(LAYER_DIR, exist_ok=True)
            with zipfile.ZipFile(setup) as z:
                with open(dll, "wb") as f:
                    f.write(z.read("ReShade64.dll"))
            self.say("ReShade: %s extracted" % RESHADE_VERSION)
        self.add(dll)
        self.record["components"]["reshade"] = RESHADE_VERSION
        manifest = {
            "file_format_version": "1.0.0",
            "layer": {
                "name": LAYER_NAME,
                "type": "GLOBAL",
                "library_path": ".\\ReShade64.dll",
                "api_version": "1.3.268",
                "implementation_version": "1",
                "description": "ReShade, installed for the Neural Lens's presenter only",
                "device_extensions": [{"name": "VK_EXT_tooling_info", "spec_version": "1",
                                       "entrypoints": ["vkGetPhysicalDeviceToolPropertiesEXT"]}],
                "disable_environment": {"DISABLE_VK_LAYER_reshade_neural_lens": "1"},
                # on only where this is set, which the presenter does for itself, so no
                # other program gets the lens's ReShade, see layer_ungated
                "enable_environment": {LAYER_GATE: "1"},
            },
        }
        with open(os.path.join(LAYER_DIR, "ReShade64.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1)
        self.add(os.path.join(LAYER_DIR, "ReShade64.json"))
        # ReShade's own setup program keeps this list, and ReShade does not read it
        self.add(write_text(os.path.join(LAYER_DIR, "ReShadeApps.ini"),
                            "Apps=%s\n" % os.path.join(self.target, "lens-presenter.exe")))

    # NVIDIA: both runtimes, hash checked. The model goes in as
    # nvngx_dlssnr_real.dll, behind the Cost Scaler: on an RTX 50 card the
    # 310.9.16 model out of NVIDIA's own package, with the package's licence
    # beside it, and on an older card, or where the package cannot be had, the
    # 310.8.SF-v2 build through the RHI manifest, see NVIDIA_PACKAGE.
    def step_nvidia(self):
        ok, detail = gpu_supported()
        if not ok:
            raise StackError("Neural Rendering needs an NVIDIA RTX card: %s" % detail)
        package = gets_package(detail)
        self.record["components"]["gpu"] = detail
        self.record["components"]["dlss"] = DLSS_VERSION
        self.say("NVIDIA: compute capability %s, Neural Rendering model %s"
                 % (detail, ("%s from NVIDIA's own package" % NVIDIA_MODEL) if package else MODEL))
        manifest = {}

        # The manifest's version names are labels its maintainer renames: on
        # 2026-09-24 310.8.SF-v2 became "310.8.2 (20/30/40/50)" while the file
        # stayed where it was. So an entry is found by the release tag in its
        # link first and by its name second, and with neither, or no manifest
        # at all, the release is fetched straight from the repository. The
        # hash check below decides whether a download is installed.
        def url_for(key, version):
            tag = "%s-%s" % (key, version)
            if not manifest:
                try:
                    manifest.update(fetch_json(SOURCES["manifest"]))
                except Exception as exc:
                    self.say("manifest unreachable (%s), fetching %s from its release" % (exc, tag))
            entries = manifest.get(key, [])
            for entry in entries:
                if "/%s/" % tag in entry.get("url", ""):
                    return entry["url"]
            for entry in entries:
                if entry.get("version") == version:
                    return entry["url"]
            return SOURCES["rhi_release"] % (tag, "nvngx_%s_%s.zip" % (key, version))

        self._from_manifest("nvngx_dlss.dll", "nvngx_dlss.dll", HASHES["nvngx_dlss.dll"], "dlss", DLSS_VERSION,
                            url_for)
        self.record["components"]["dlssnr"] = self._model(package, url_for)

    def _from_manifest(self, name, dest_name, want, key, version, url_for):
        """One of NVIDIA's files the RHI manifest serves: the copy the user
        pointed at, the one already in place, or a download, each held to its
        hashes."""
        dest = os.path.join(self.target, dest_name)
        given = self.given.get(name)
        if given:
            got = sha256(given)
            if got not in want:
                raise StackError("%s is not a %s build this stack knows\n"
                                 "  yours    %s\n  known    %s" % (given, version, got, ", ".join(want)))
            shutil.copy2(given, dest)
            self.say("%s: using your copy, hash verified" % name)
        elif os.path.isfile(dest) and sha256(dest) in want:
            self.say("%s: already present and verified" % dest_name)
        else:
            z = fetch(url_for(key, version), os.path.join(CACHE_DIR, "%s_%s.zip" % (key, version)),
                      self.log, "%s %s" % (name, version))
            with zipfile.ZipFile(z) as zf:
                member = next(i for i in zf.infolist() if i.filename.lower().endswith(name))
                with open(dest + ".part", "wb") as f:
                    f.write(zf.read(member))
            got = sha256(dest + ".part")
            if got not in want:
                os.remove(dest + ".part")
                raise StackError("%s downloaded from the manifest matches no known hash\n"
                                 "  got      %s\n  known    %s\nNot installed. The repository may "
                                 "have published a new build; the lens's release notes will say when "
                                 "one is verified." % (name, got, ", ".join(want)))
            os.replace(dest + ".part", dest)
            self.say("%s: downloaded, hash verified" % dest_name)
        self.add(dest)

    def _model(self, package, url_for):
        """The model into the stack folder, and which one it is. A copy the user
        pointed at may be either known model. Otherwise, with package, NVIDIA's
        model as it is in place with its licence, or out of NVIDIA's package,
        and where that cannot be had the SF-v2 build through the manifest, which
        a line says. Without package the SF-v2 build. NVIDIA's licence stays in
        the folder only beside NVIDIA's model."""
        dest = os.path.join(self.target, "nvngx_dlssnr_real.dll")
        licence = os.path.join(self.target, NVIDIA_LICENCE)
        nvidia, sf = HASHES["nvngx_dlssnr.dll"][NVIDIA_MODEL], HASHES["nvngx_dlssnr.dll"][MODEL]
        given = self.given.get("nvngx_dlssnr.dll")
        if given:
            got = sha256(given)
            if got not in nvidia + sf:
                raise StackError("%s is not a model build this stack knows\n"
                                 "  yours    %s\n  known    %s" % (given, got, ", ".join(nvidia + sf)))
            shutil.copy2(given, dest)
            model = NVIDIA_MODEL if got in nvidia else MODEL
            self.say("nvngx_dlssnr.dll: using your copy, hash verified, the %s model" % model)
            self.add(dest)
            if model == MODEL:
                self._drop_licence()
            elif os.path.isfile(licence):
                self.add(licence)
            return model
        if package:
            present = os.path.isfile(dest) and sha256(dest) in nvidia
            if present and os.path.isfile(licence):
                self.say("nvngx_dlssnr_real.dll: NVIDIA's %s model, already present and verified" % NVIDIA_MODEL)
                self.add(dest)
                self.add(licence)
                return NVIDIA_MODEL
            try:
                self._from_package(dest, licence)
                return NVIDIA_MODEL
            except StackError as exc:
                why = str(exc).splitlines()[0]
            if present:
                # the model is there and checks out, and only its licence could not be put beside it
                self.say("NVIDIA's package could not be used (%s), so its licence is not in the stack folder. "
                         "The %s model in place is kept." % (why, NVIDIA_MODEL))
                self.add(dest)
                return NVIDIA_MODEL
            self.say("NVIDIA's package could not be used (%s), so the setup takes the %s model through the RHI "
                     "manifest instead, which holds %s alone." % (why, MODEL, LARGE_SAID))
        self._from_manifest("nvngx_dlssnr.dll", "nvngx_dlssnr_real.dll", sf, "dlssnr", MODEL, url_for)
        self._drop_licence()
        return MODEL

    def _from_package(self, dest, licence):
        """NVIDIA's package, fetched into a folder of its own among the
        downloads and held to its size and hash, and the model and the licence
        taken out of it there as data, the model held to its hash, then put into
        the stack folder. StackError when any of it fails, with nothing in the
        stack folder changed."""
        p = NVIDIA_PACKAGE
        folder = os.path.join(CACHE_DIR, PACKAGE_FOLDER)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, p["name"])
        if not (os.path.isfile(path) and os.path.getsize(path) == p["size"] and sha256(path) in p["sha256"]):
            fetch(p["url"], path, self.log, "NVIDIA's model package")
            size = os.path.getsize(path)
            if size != p["size"]:
                try:
                    os.remove(path)
                except OSError:
                    pass
                raise StackError("it came to %d bytes, where NVIDIA's package is %d" % (size, p["size"]))
            check_hash(path, p["sha256"], "NVIDIA's package")
        model_part = os.path.join(folder, "nvngx_dlssnr.dll")
        licence_part = os.path.join(folder, "LICENSE.txt")
        try:
            _size, got = extract_7z(path, p["model"], model_part)
            if got not in HASHES["nvngx_dlssnr.dll"][NVIDIA_MODEL]:
                raise StackError("the model in it matches no known hash, %s" % got)
            extract_7z(path, p["licence"], licence_part)
            try:
                os.replace(model_part, dest)    # the downloads and the stack share a drive, as installed
            except OSError:
                shutil.copyfile(model_part, dest + ".part")
                os.replace(dest + ".part", dest)
            shutil.copyfile(licence_part, licence)
        except OSError as exc:
            raise StackError("its files could not be taken out, %s" % exc)
        finally:
            for part in (model_part, licence_part, dest + ".part"):
                try:
                    os.remove(part)
                except OSError:
                    pass
        self.add(dest)
        self.add(licence)
        self.say("nvngx_dlssnr_real.dll: NVIDIA's %s model out of NVIDIA's own package, hash verified, with "
                 "NVIDIA's licence beside it as %s" % (NVIDIA_MODEL, NVIDIA_LICENCE))

    def _drop_licence(self):
        """NVIDIA's licence out of the stack folder, where the model is not
        the one it came with."""
        try:
            os.remove(os.path.join(self.target, NVIDIA_LICENCE))
            self.say("%s removed, since the model it came with is not in the stack" % NVIDIA_LICENCE)
        except OSError:
            pass

    # DLSSNR-Cost-Scaler: the proxy as nvngx_dlssnr.dll, forwarding to the model
    def step_cost_scaler(self):
        name = "DLSSNR-Cost-Scaler-v%s.zip" % COST_SCALER_VERSION
        z = fetch(SOURCES["cost_scaler"], os.path.join(CACHE_DIR, name), self.log,
                  "DLSSNR Cost Scaler " + COST_SCALER_VERSION)
        check_hash(z, HASHES["cost-scaler.zip"], name)
        dest = os.path.join(self.target, "nvngx_dlssnr.dll")
        ini_path = os.path.join(self.target, "nvngx_dlssnr.ini")
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            dll = next((n for n in names if n.lower().endswith("nvngx_dlssnr.dll")), None)
            ini = next((n for n in names if n.lower().endswith("nvngx_dlssnr.ini")), None)
            if not dll or not ini:
                raise StackError("the Cost Scaler's archive holds no nvngx_dlssnr.dll or nvngx_dlssnr.ini")
            self._extract(zf, dll, dest + ".part")
            check_hash(dest + ".part", HASHES["cost-scaler.dll"], "the Cost Scaler's nvngx_dlssnr.dll")
            os.replace(dest + ".part", dest)
            self.add(dest)
            if os.path.isfile(ini_path):
                kept = " Its settings were already there and are kept."
            else:
                # latin-1 both ways, so every byte of its comments survives
                text = set_ini_values(zf.read(ini).decode("latin-1"), COST_SCALER_SETTINGS)
                with open(ini_path, "wb") as f:
                    f.write(text.encode("latin-1"))
                kept = ""
            self.add(ini_path)
        self.record["components"]["cost_scaler"] = COST_SCALER_VERSION
        self.say("DLSSNR Cost Scaler %s: in front of the model, off until the lens asks for it.%s"
                 % (COST_SCALER_VERSION, kept))

    def step_feeder(self):
        rel = fetch_json(SOURCES["feeder_api"])
        asset = next((a for a in rel.get("assets", []) if re.match(r"^DLSS5-Feeder-.*\.zip$", a["name"])), None)
        if not asset:
            raise StackError("no DLSS5-Feeder zip in its latest release")
        self.record["components"]["feeder"] = rel.get("tag_name")
        z = fetch(asset["browser_download_url"], os.path.join(CACHE_DIR, asset["name"]), self.log,
                  "DLSS5-Feeder " + rel.get("tag_name", ""))
        # the maintainer prints each zip's SHA-256 in the release notes, and fake
        # copies of the Feed exist, so the zip must match that line or a hash
        # this file knows before anything is taken out of it
        verify_feeder_zip(z, asset["name"], rel.get("body"))
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            addon = next(n for n in names if n.lower().endswith("dlss5-feed.addon64"))
            fx = next(n for n in names if n.lower().endswith("dlss5_feed.fx"))
            self.add(self._extract(zf, addon, os.path.join(self.target, "dlss5-feed.addon64")))
            self.add(self._extract(zf, fx, os.path.join(self.target, "reshade-shaders", "Shaders", "DLSS5_Feed.fx")))
        self.say("DLSS5-Feeder: %s" % rel.get("tag_name"))

    def step_renodx(self):
        """Both builds of the Home menu add-on, each zip fetched into the stack's
        addons folder and checked by hash, where both stay for the lens to swap
        between, and the chosen build's add-on put in place, see ADDON_BUILDS.
        The choice is self.addon where it is set, as --addon sets it, and else
        the lens's own, see addon_choice.

        The add-on's section of an existing ReShade.ini, which step_config
        keeps, is given to the build put in place here first: one written for
        the other build is carried over, as a switch carries it, with the
        section as it was kept in the addons folder as that build's copy, so
        5.2.1 never resets it and the 8.5 build never migrates it, see
        addon_switch. Its ConfigVersion says which build it was written for,
        or else the add-on that was in place does. A new install of the 8.5
        build gets a section of ConfigVersion 7 and NRPreset=1, the template's
        two lines at that build's version, which step_config keeps in place of
        the template's. And the copies of ReShade.ini that the
        8.5 build makes before it migrates a section go, since the addons
        folder keeps each build's section."""
        build = self.addon = addon_build_named(getattr(self, "addon", None) or addon_choice())
        was = addon_in_place(self.target)
        others = [b for b in ADDON_BUILDS if b != build]
        for b in [build] + others:
            self.add(addon_zip(self.target, b, self.log))
        dest = os.path.join(self.target, "renodx-dlss5.addon64")
        write_bytes(dest + ".part", addon_file(addon_zip_path(self.target, build), build))
        os.replace(dest + ".part", dest)
        self.add(dest)
        self.record["components"]["renodx"] = ADDON_BUILDS[build]["version"]
        self.say("RenoDX DLSS 5 add-on: %s, hash verified" % ADDON_BUILDS[build]["version"])
        for b in others:
            self.say("RenoDX DLSS 5 add-on %s: kept in the %s folder for the choice in Settings, hash verified"
                     % (ADDON_BUILDS[b]["version"], ADDON_DIR))
        ini = os.path.join(self.target, "ReShade.ini")
        now = ini_section(ini)
        if now is None:
            if ADDON_BUILDS[build]["schema"] != "2":
                # a new install given the 8.5 build: a section of that build's own
                # ConfigVersion and the large network, the two lines the
                # template gives 5.2.1, so step_config keeps it in place of the
                # template's and has nothing to say about settings kept or the
                # network set, since there were none
                ini_put_section(ini, [("ConfigVersion", ADDON_BUILDS[build]["schema"]), (MODEL_KEY, LARGE)])
                self.stub_section = True
        else:
            src = section_build(now) or (was if was in ADDON_BUILDS else build)
            if src != build:
                addon_keep(self.target, src, now)
                ini_put_section(ini, section_convert(now, src, build, addon_kept(self.target, build)))
                self.say("RenoDX DLSS 5 add-on: its settings in the existing ReShade.ini carried over from %s to "
                         "%s, and kept as they were for %s in the %s folder"
                         % (addon_words(src), addon_words(build), addon_words(src), ADDON_DIR))
        gone = 0
        for p in addon_backups(self.target):
            try:
                os.remove(p)
                gone += 1
            except OSError:
                pass
        if gone:
            self.say("RenoDX DLSS 5 add-on: the %s of ReShade.ini that the 8.5 build made before changing its "
                     "section %s removed, since the %s folder keeps each build's section"
                     % ("copy" if gone == 1 else "%d copies" % gone, "was" if gone == 1 else "were", ADDON_DIR))

    def step_shaders(self):
        base = os.path.join(self.target, "reshade-shaders", "Shaders")
        textures = os.path.join(self.target, "reshade-shaders", "Textures")
        self.add(fetch(SOURCES["vort"] + "Shaders/vort_Motion.fx", os.path.join(base, "vort_Motion.fx"),
                       self.log, "vort_Motion.fx"))
        includes = [e["name"] for e in fetch_json(SOURCES["vort_api"])
                    if e.get("type") == "file" and e["name"].startswith("vort_") and e["name"].endswith(".fxh")]
        if len(includes) < 10:
            raise StackError("the VORT repository listed only %d include files" % len(includes))
        for name in includes:
            self.add(fetch(SOURCES["vort"] + "Shaders/Includes/" + name, os.path.join(base, "Includes", name),
                           self.log, name))
        for name in VORT_TEXTURES:
            self.add(fetch(SOURCES["vort"] + "Textures/" + name, os.path.join(textures, name), self.log, name))
        for name in HEADER_FILES:
            self.add(fetch(SOURCES["headers"] + name, os.path.join(base, name), self.log, name))
        self.say("shaders: VORT (MIT, its motion vector code CC BY-NC 4.0) fetched as the alternative "
                 "estimator, %d includes and its texture, and ReShade's headers" % len(includes))
        for name in DRME_FILES:
            self.add(fetch(SOURCES["drme"] + name, os.path.join(base, name), self.log, name))
        self.say("shaders: ReshadeMotionEstimation by Jakob Wapenhensch (CC BY-NC 4.0)")
        self.record["components"]["motion_vectors"] = {"drme": "ReshadeMotionEstimation", "vort": "VORT"}[self.provider]
        self.say("motion vectors: %s will provide them" % self.record["components"]["motion_vectors"])

    def step_config(self):
        # the templates are written for VORT; the chosen provider is substituted
        ini, preset = RESHADE_INI, RESHADE_PRESET
        if self.provider == "drme":
            ini = ini.replace("DLSS5_MV_PROVIDER=2,V_MV_MODE=1", "DLSS5_MV_PROVIDER=0")
            preset = preset.replace("vort_MotionEffects@vort_Motion.fx", "DRME@MotionEstimation.fx")
        path = os.path.join(self.target, "ReShade.ini")
        kept = self._addon_section(path)
        if kept:
            ini = ini.replace(ADDON_SECTION + "\nConfigVersion=2\nNRPreset=1\n",
                              ADDON_SECTION + "\n" + "\n".join(self._model_preset(kept)) + "\n")
            # not for the section step_renodx itself wrote a moment ago for a
            # new install of the 8.5 build, which holds no settings of anyone's
            if not getattr(self, "stub_section", False):
                self.say("config: the Neural Rendering add-on's settings in the existing ReShade.ini are kept")
        # the template's section starts on the large network, and an
        # existing one is on it now unless it was set before, see _model_preset
        self.record[PRESET_DONE] = True
        # the template goes in as write_text writes it, and the lens's own
        # section of the existing file after it, byte for byte, see _lens_section
        data = ini.replace("\n", "\r\n").encode("utf-8")
        own = self._lens_section(path)
        if own:
            data += b"\r\n" + own
            self.say("The lens's own section of the existing ReShade.ini, with the values the passes from the "
                     "second on have of their own, is kept as it was")
        self.add(write_bytes(path, data))
        self.add(write_text(os.path.join(self.target, "ReShadePreset.ini"), preset))
        self.add(write_text(os.path.join(self.target, "dlss5-feed.cfg"), FEED_CFG))
        self.say("config: ReShade, the preset and the feed written")

    def _model_preset(self, lines):
        """The lines of the add-on's section with NRPreset at LARGE where it
        is 0, not a number or missing, and a line that says so: on the 310.9.16
        model 0 runs the small FP8 network, where every model before ran the
        large one, see MODEL_KEY. Once only: where the record of an earlier
        run says it was done, see PRESET_DONE, the lines come back as they are,
        so a 0 chosen since, in the add-on's overlay, stays."""
        if self.earlier.get(PRESET_DONE):
            return lines
        at, value = None, None
        for i, line in enumerate(lines):
            key, sign, rest = line.partition("=")
            if sign and key.strip().lower() == MODEL_KEY.lower():
                at, value = i, rest.strip()
        try:
            number = float(value) if value is not None else 0.0
        except ValueError:
            number = 0.0
        if number != 0.0:
            return lines
        out = list(lines)
        if at is None:
            out.append("%s=%s" % (MODEL_KEY, LARGE))
        else:
            out[at] = "%s=%s" % (MODEL_KEY, LARGE)
        self.say("config: %s in the add-on's section was %s, which on NVIDIA's %s model runs %s, "
                 "so it is now %s, %s, as before"
                 % (MODEL_KEY, "missing" if at is None else value, NVIDIA_MODEL, SMALL_SAID, LARGE, LARGE_SAID))
        return out

    @staticmethod
    def _addon_section(path):
        """The lines of the add-on's section in an existing ReShade.ini, or None."""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            return None
        out, inside = [], False
        for line in lines:
            bare = line.strip()
            if bare.startswith("["):
                if inside:
                    break
                inside = bare.lower() == ADDON_SECTION.lower()
                continue
            if inside and bare:
                out.append(bare)
        return out or None

    @staticmethod
    def _lens_section(path):
        """The lens's own section in an existing ReShade.ini as the file has it,
        or b"" where the file has none or cannot be read. That is each line from
        the line with the section's name to its last line that is not blank,
        with the line's own ending, so the values come back byte for byte. A
        line that starts with a bracket names a section, by what follows the
        bracket up to the first closing one, or to the line's end where there is
        none, without the spaces around it and whatever its case. Windows reads
        the name that way for the fast engine, and the lens finds the section
        that way when it writes to it, so a name line written by hand with a
        space or a comment in it is kept as well, and after a repair the engine
        and the lens read what they read before. A file that has the section
        more than once gives each, in the file's order, with a blank line
        between them."""
        try:
            with open(path, "rb") as f:
                lines = f.read().splitlines(True)
        except OSError:
            return b""
        name = LENS_SECTION.strip("[]").lower().encode("ascii")
        found, inside = [], None
        for line in lines:
            bare = line.strip()
            if bare.startswith(b"["):
                end = bare.find(b"]")
                title = bare[1:] if end < 0 else bare[1:end]
                inside = [line] if title.strip().lower() == name else None
                if inside is not None:
                    found.append(inside)
            elif inside is not None:
                inside.append(line)
        for section in found:
            while len(section) > 1 and not section[-1].strip():
                section.pop()       # the blank lines before the next section
        return b"\r\n".join(b"".join(section) for section in found)

    def step_layer(self):
        manifest = os.path.join(LAYER_DIR, "ReShade64.json")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, manifest, 0, winreg.REG_DWORD, 0)
        self.record["registry"].append(manifest)
        self.say("Vulkan layer: registered for this user as %s" % LAYER_NAME)

    def write_record(self):
        path = os.path.join(self.target, "install-record.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.record, f, indent=1)

    @staticmethod
    def _extract(zf, member, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(zf.read(member))
        return dest


# ---------------------------------------------------------------- the layer's limit
def layer_ungated():
    """The descriptions of the lens's layer, registered for this user, that
    would switch it on in every program: the paths of those that name the
    lens's layer and have no enable_environment for LAYER_GATE. Empty where
    every one waits for the presenter to ask, or none is registered.

    The layer is ReShade, and it belongs in the lens's own presenter alone. A
    description without the switch, which 0.5.1 wrote and an update with the
    stack setup left out keeps, has the Vulkan loader put ReShade into every
    program that uses Vulkan, games included. step_reshade writes the switch.
    The loader passes over a value that is not 0, and so does this. Only the
    registry and the descriptions are read. The lens asks this as it starts,
    and --verify says what it found."""
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    name, data, kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if kind != winreg.REG_DWORD or data != 0:
                    continue
                try:
                    with open(name, encoding="utf-8-sig") as f:
                        described = json.load(f)
                    layers = described.get("layers") or [described.get("layer") or {}]
                except (OSError, ValueError, AttributeError):
                    continue
                for layer in layers:
                    if isinstance(layer, dict) and layer.get("name") == LAYER_NAME and LAYER_GATE not in (
                            layer.get("enable_environment") or {}):
                        found.append(name)
                        break
    except OSError:
        pass
    return found


def layer_line(ungated):
    """The self test's line on the layer's limit, for layer_ungated's answer.
    The setup writes only this copy's own description, LAYER_DIR's, so a path
    of another copy of the lens is said to be that copy's, which this setup
    does not change, and where both are listed, the line names which one the
    setup writes."""
    if not ungated:
        return "    Vulkan layer: on only where the lens's presenter asks for it"
    own = os.path.normcase(os.path.abspath(os.path.join(LAYER_DIR, "ReShade64.json")))
    mine = [p for p in ungated if os.path.normcase(os.path.abspath(p)) == own]
    others = [p for p in ungated if p not in mine]
    line = ("    Vulkan layer: NOT LIMITED TO THE LENS. %s %s no enable_environment, so Vulkan loads the lens's "
            "ReShade into every program that uses Vulkan, games included."
            % (" and ".join(ungated), "has" if len(ungated) == 1 else "have"))
    if mine:
        line += (" Running the stack setup again writes the limit%s."
                 % (" into this copy's own description, %s" % mine[0] if others else ""))
    if others:
        line += (" %s %s to another copy of the lens, and the stack setup of this copy does not change %s."
                 % (" and ".join(others), "belongs" if len(others) == 1 else "belong",
                    "it" if len(others) == 1 else "them"))
    return line


def layer_unregister(path):
    """Delete this user's registration of a description of the lens's layer,
    the ImplicitLayers value named by its path, for one that another copy of
    the lens registered, which the lens asks about as it starts. Only a value
    whose description names LAYER_NAME is deleted, so nothing but the lens's
    own layer is touched. Returns whether it went."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            described = json.load(f)
        layers = described.get("layers") or [described.get("layer") or {}]
    except (OSError, ValueError, AttributeError):
        return False
    if not any(isinstance(layer, dict) and layer.get("name") == LAYER_NAME for layer in layers):
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, path)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- verify
def runs_elevated():
    """Whether this process runs at high integrity or above, as a program run as
    administrator does. The Vulkan loader makes the same test in the program it
    loads into, and there it reads no layer registered under HKEY_CURRENT_USER,
    the only place the setup registers the lens's, so a presenter this process
    starts gets no ReShade. IsUserAnAdmin, which agrees for an administrator run
    as administrator, answers when the token cannot be read."""
    import ctypes
    from ctypes import wintypes
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
        advapi32.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD))
        advapi32.GetSidSubAuthorityCount.argtypes = (ctypes.c_void_p,)
        advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        advapi32.GetSidSubAuthority.argtypes = (ctypes.c_void_p, wintypes.DWORD)
        advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            size = wintypes.DWORD()
            advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))  # TokenIntegrityLevel
            label = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(token, 25, label, size, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            sid = ctypes.cast(label, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_MANDATORY_LABEL.Label.Sid
            if not sid:
                raise OSError("the token has no integrity label")
            last = advapi32.GetSidSubAuthorityCount(sid)[0] - 1
            return advapi32.GetSidSubAuthority(sid, last)[0] >= 0x3000  # SECURITY_MANDATORY_HIGH_RID
        finally:
            kernel32.CloseHandle(token)
    except Exception:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False


def verify(target, log=None, seconds=9.0):
    """Run the presenter on a still and read what ReShade says.

    The presenter is what the lens runs, so the self test runs it too, on its
    pattern source rather than a capture: a still with detail in a 960x540
    window at the top left of the primary monitor, long enough for the Feed's
    warm up and the first Neural Rendering evaluations. The verdict is read
    from ReShade.log and the Feed's log.
    """
    cmd = presenter_command(target)
    if not os.path.isfile(cmd[0]):
        return False, "FAIL: no lens-presenter.exe in %s" % target
    logfile = os.path.join(target, "ReShade.log")
    proxy_log = os.path.join(target, "nvngx_dlssnr_proxy.log")
    for stale in (logfile, proxy_log):
        try:
            os.remove(stale)
        except OSError:
            pass
    env = dict(os.environ, DISABLE_DLSS5_VK_BRIDGE="1")
    err = tempfile.TemporaryFile()
    had = set(addon_backups(target))
    started = time.time()
    proc = subprocess.Popen(cmd + ["--source", "pattern", "--at", "40", "40", "--size", "960", "540",
                                   "--title", "NeuralLensSelfTest"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, cwd=target,
                            env=env, text=True, creationflags=NO_WINDOW)
    said = []

    def drain():
        for line in proc.stdout:
            said.append(line.rstrip())

    threading.Thread(target=drain, daemon=True).start()
    say(log, "    self test: a presenter window at the top left for %.0f seconds" % seconds)
    while time.time() - started < seconds and proc.poll() is None:
        time.sleep(0.2)
    early = proc.poll()
    try:
        proc.stdin.write("quit\n")
        proc.stdin.flush()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    # a copy of ReShade.ini the 8.5 build made during the test goes again. A
    # section of its own schema gives it no reason to, see addon_backups
    for p in set(addon_backups(target)) - had:
        try:
            os.remove(p)
        except OSError:
            pass
    if early is not None:
        err.seek(0)
        tail = err.read().decode("utf-8", "replace").strip()[-900:]
        return False, ("FAIL: the presenter stopped after %.0f seconds with exit code %s.\n%s"
                       % (time.time() - started, early, tail or "\n".join(said[-5:]) or "It printed nothing."))
    try:
        text = open(logfile, encoding="utf-8", errors="replace").read()
    except OSError:
        if runs_elevated():
            # the presenter runs with this process's rights, so the layer this user has
            # registered never loads in it, and the checks below would all hold
            return False, ("FAIL: ReShade wrote no log at %s, so it did not start in the presenter. This setup "
                           "runs as administrator, and in a program that runs as administrator Vulkan reads no "
                           "layer registered for one user. Run the stack setup again without administrator "
                           "rights. In an account where every program runs as administrator, as with User "
                           "Account Control fully off, ReShade cannot start in the lens." % logfile)
        # ReShade 6.8 never reads ReShadeApps.ini. The layer loads where the variable its
        # description's enable_environment names is set, and ReShade then starts only
        # beside a ReShade.ini, see layer_ungated
        return False, ("FAIL: ReShade wrote no log at %s, so it did not start in the presenter. Check that the "
                       "layer's description %s is registered for this user under HKEY_CURRENT_USER\\%s with the "
                       "value 0 and carries enable_environment with %s, the switch the presenter sets for itself. "
                       "Check too that ReShade.ini is beside %s, since ReShade starts only where it finds one."
                       % (logfile, os.path.join(LAYER_DIR, "ReShade64.json"), LAYER_KEY, LAYER_GATE, cmd[0]))
    created = "feature=18" in text and "feature 18 created" in text
    # the add-on logs the 1st, 60th and 600th evaluation and none after them,
    # counting its pre-SR and inline evaluations apart, so a session that went
    # from pre-SR to inline can log up to six, and the highest count it logged is
    # how many there were at least
    counts = [int(c) for c in re.findall(r"feature 18 evaluation succeeded \(count=(\d+)", text)]
    evaluated = max(counts) if counts else len(re.findall(r"feature 18 evaluation succeeded", text))
    failed = re.search(r"feature 18 create failed with (0x[0-9a-fA-F]+)", text)
    addons = ("DLSS 5 Neural Rendering" in text, "DLSS 5 Feed" in text)
    lines = ["    ReShade attached: yes",
             "    add-ons loaded: Neural Rendering %s, Feed %s" % tuple("yes" if a else "NO" for a in addons),
             # which of the two builds of the Home menu add-on is in place, see ADDON_BUILDS
             "    Neural Rendering add-on: %s" % addon_words(addon_in_place(target))]
    # the Cost Scaler logs as it loads, whether it is switched on or off
    try:
        proxy = open(proxy_log, encoding="utf-8", errors="replace").read()
        lines.append("    Cost Scaler: %s" % ("loaded, in front of the model" if "Loaded real module successfully"
                                                 in proxy else "its log says it did not load the model"))
    except OSError:
        if os.path.isfile(os.path.join(target, "nvngx_dlssnr_real.dll")):
            lines.append("    Cost Scaler: it wrote no log")
    # which model, NVIDIA's with both networks or the SF-v2 build with one, see model_in
    lines.append(model_line(target))
    # A still needs no motion vectors, so Neural Rendering can run with the
    # provider missing and nobody would know until something moved. The Feed
    # says which provider it found; read that rather than trust the picture.
    try:
        feed = open(os.path.join(target, "dlss5-feed.log"), encoding="utf-8", errors="replace").read()
        # the Feed's "effects:" line names the provider it found; its warnings
        # mention the setting too, "use another provider (VORT:
        # DLSS5_MV_PROVIDER=2)", so they are not the line to read
        prov = [l for l in feed.splitlines() if "effects:" in l and "DLSS5_MV_PROVIDER=" in l]
        last = prov[-1].split("DLSS5_MV_PROVIDER=", 1)[-1] if prov else ""
        if not prov or "-> none" in last:
            lines.append("    motion vectors: NO PROVIDER, so anything that moves would smear. "
                         "The motion vector shader did not compile or was not found: %s" % (last[:90] or "no Feed log"))
            return False, "\n".join(lines)
        name = re.search(r"->\s*([^(,]+)", last)
        name = name.group(1).strip() if name else last.split(",", 1)[0][:60]
        if "FAILED TO COMPILE" in last:
            # measured in the lens: DRME's frame save pass fails on ReShade 6.8 and
            # the Feed says it then writes nothing, yet the Feed's own motion vector
            # probe reads real vectors whenever the picture moves
            lines.append("    motion vectors: %s. The Feed's log reports one of its passes failing to "
                         "compile on this ReShade, which is expected, and the rest still deliver "
                         "vectors once something moves." % name)
        else:
            lines.append("    motion vectors: %s" % name)
    except OSError:
        lines.append("    motion vectors: the Feed wrote no log")
        return False, "\n".join(lines)
    if failed:
        lines.append("    Neural Rendering: FAILED to start, %s" % failed.group(1))
        if failed.group(1).lower() == "0xbad00001" and model_in(target) == NVIDIA_MODEL:
            lines.append("    that code means the model refused to run on this card. NVIDIA's %s model is "
                         "fetched for the RTX 50 series, and the %s build, which covers RTX 20 through 50, "
                         "can be given to the stack setup with --dlssnr." % (NVIDIA_MODEL, MODEL))
        elif failed.group(1).lower() == "0xbad00001":
            lines.append("    that code means the model refused to run on this card. The 310.8.SF-v2 "
                         "build in use is meant to cover RTX 20 through 50.")
        return False, "\n".join(lines)
    if created and evaluated:
        lines.append("    Neural Rendering: running, at least %d evaluations" % evaluated)
        return True, "\n".join(lines)
    lines.append("    Neural Rendering: never started (no feature 18 in the log). Log: %s" % logfile)
    return False, "\n".join(lines)


# ---------------------------------------------------------------- uninstall
def _unregister_stray(log=None):
    """Delete any layer value that points inside this install's layer folder,
    whether or not a record names it. The value name is the manifest path, so
    everything under LAYER_DIR is ours and nothing else is touched."""
    removed = []
    prefix = os.path.normcase(LAYER_DIR) + os.sep
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            names = []
            i = 0
            while True:
                try:
                    names.append(winreg.EnumValue(k, i)[0])
                except OSError:
                    break
                i += 1
            for name in names:
                if os.path.normcase(name).startswith(prefix):
                    try:
                        winreg.DeleteValue(k, name)
                        removed.append(name)
                        say(log, "unregistered %s" % name)
                    except OSError:
                        pass
    except OSError:
        pass
    return removed


def uninstall(target=DEFAULT_TARGET, log=None, keep=()):
    """Remove what the install record in target lists, the layer registration,
    and what running the stack and the fast engine wrote. Paths in keep are
    left in place."""
    path = os.path.join(target, "install-record.json")
    try:
        record = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        # No record, so no files are known. The layer value can still be there:
        # an install stopped after step_layer and before write_record registered
        # it and never recorded it, and left alone it would point the Vulkan
        # loader at a manifest the uninstaller is about to delete.
        stray = _unregister_stray(log)
        raise StackError("no install record in %s, nothing known to remove%s" % (
            target, "; removed %d layer value(s) it left behind" % len(stray) if stray else ""))
    for value in record.get("registry", []):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, value)
            say(log, "unregistered %s" % value)
        except OSError:
            pass
    _unregister_stray(log)
    kept = {os.path.normcase(os.path.abspath(k)) for k in keep}
    for f in record.get("files", []):
        if os.path.normcase(os.path.abspath(f)) in kept:
            continue
        try:
            os.remove(f)
        except OSError:
            pass
    # what running the stack wrote: the logs and their rotations, the Cost
    # Scaler's log, the 8.5 add-on's journal and its copies of ReShade.ini, and
    # the shader cache of the mpv that 0.1.0 ran. The addons folder goes whole,
    # the copy of the add-on's section each build keeps there included
    for extra in ("ReShadePreset.ini", "ReShade.ini", "install-record.json", ADDON_JOURNAL) + tuple(
            f for f in os.listdir(target)
            if f.startswith(("ReShade.log", "dlss5-feed.log", "nvngx_dlssnr_proxy.log", ADDON_BACKUP))):
        try:
            os.remove(os.path.join(target, extra))
        except OSError:
            pass
    shutil.rmtree(os.path.join(target, ADDON_DIR), ignore_errors=True)
    shutil.rmtree(os.path.join(target, "portable_config", "cache"), ignore_errors=True)
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
    # what the fast engine wrote: its copy of the proxy's ini beside lens-fast.exe,
    # made from the stack's, and the runtime's logs in the lens's data folder. A
    # data_dir moved out of the lens's folder is left alone, like the rest of it.
    for d in fast_engine_dirs(target):
        try:
            os.remove(os.path.join(d, "nvngx_dlssnr.ini"))
        except OSError:
            pass
    shutil.rmtree(os.path.join(APP_DIR, "data", "logs", "fast"), ignore_errors=True)
    for d in (target, record.get("layer_dir", LAYER_DIR)):
        for root, dirs, files in os.walk(d, topdown=False):
            for sub in dirs:
                try:
                    os.rmdir(os.path.join(root, sub))
                except OSError:
                    pass
        try:
            os.rmdir(d)
        except OSError:
            pass
    say(log, "removed what the record listed from %s" % target)


# ---------------------------------------------------------------- wizard
def wizard(parent=None, target=DEFAULT_TARGET, look=None):
    """A window that runs the install and shows what it is doing.

    Returns the folder the stack was installed into when it installed and
    passed the self test, otherwise False. The install runs on a thread; the
    window only ever appends to its log from the mainloop, so it stays
    responsive while the download comes down.

    look is the lens's look, neural_lens.LOOK, which the lens hands over, as
    this module imports nothing of the lens. The window then takes the ten
    colours of the look's theme, and its caption takes the look's colours
    before the window is first seen, see Look.dress. A drawn look also lays
    it out as that look's dialogs, in their type, wells and buttons, see
    Look.setup_shell. Without a look, as from source, it keeps the colours it
    always had.
    """
    import queue
    import tkinter as tk
    from tkinter import filedialog

    if look is None:
        BG, FG, DIM, ACCENT, WARN = "#1b2430", "#cbd5e1", "#64748b", "#4ade80", "#fbbf24"
        WELL, RAISED = "#0b1220", "#334155"     # the fields and the log, and the buttons other than Set it up
        PRESSED = {}                            # a button pressed in Windows' own colours, as always
    else:
        ten = look.legacy
        BG, FG, DIM, ACCENT, WARN = ten["bg"], ten["fg"], ten["dim"], ten["accent"], ten["warn"]
        WELL, RAISED = ten["field"], ten["hover"]
        # pressed, a button takes the window buttons' shade, as the lens's own buttons do
        PRESSED = {"activebackground": ten["cap"], "activeforeground": FG}
    supported, detail = gpu_supported()
    root = tk.Toplevel(parent) if parent else tk.Tk()
    if look is not None:
        root.withdraw()                 # first seen with its caption in the look's colours, see the foot
    root.title("Neural Lens: set up the neural stack")
    try:
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        root.iconbitmap(os.path.join(base, "assets", "neural-lens.ico"))
    except Exception:
        pass
    root.configure(bg=BG)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    # a drawn look lays the window out as its dialogs, see Look.setup_shell,
    # and makes the footer its buttons go into now, so they lie above it.
    # Without a look, in the classic look and where the look cannot, the
    # window is laid out as it always was
    shell = None
    if look is not None and not look.classic:
        try:
            shell = look.setup_shell(root)
        except Exception:
            shell = None
    package = supported and gets_package(detail)
    intro = ("The lens needs NVIDIA's DLSS Neural Rendering stack. Nothing of it is bundled: about "
             "%d MB is downloaded from the projects that publish each part, into the lens's own "
             "folder, and registered for your user only. No administrator prompt.\n\n"
             % (DOWNLOAD_MB_PACKAGE if package else DOWNLOAD_MB)
             + (("This card reports compute capability %s, which is supported. The model comes from NVIDIA's "
                 "own package and holds %s and %s, which the lens's Model setting chooses between."
                 % (detail, LARGE_SAID, SMALL_SAID)) if package else
                ("This card reports compute capability %s, which is supported. The model is the %s build, "
                 "which holds %s. NVIDIA made %s for the RTX 50 series."
                 % (detail, MODEL, LARGE_SAID, SMALL_SAID)) if supported else
                "Neural Rendering cannot run on this machine: %s." % detail))
    tk.Label(root, text=intro, bg=BG, fg=FG, justify="left", wraplength=620,
             font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 8))
    tk.Label(root, text="Goes into", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
        row=1, column=0, sticky="w", padx=14)
    tk.Label(root, text=target, bg=BG, fg=FG, font=("Consolas", 9), anchor="w").grid(
        row=1, column=1, columnspan=2, sticky="w", padx=(6, 14))
    # every variable is made on this window's own Tk. At the offer the lens
    # makes when its stack is incomplete, the lens's root already exists and is
    # the default root, so a variable without a master lived there while the
    # entries lived here: the fields showed empty and anything typed was never seen
    have = {"nvngx_dlssnr.dll": tk.StringVar(master=root), "nvngx_dlss.dll": tk.StringVar(master=root)}
    tk.Label(root, text="If you already have NVIDIA's DLLs, point at them and copies are used instead "
                        "of downloaded, once their hashes check out. Otherwise leave these empty.",
             bg=BG, fg=DIM, justify="left", wraplength=620, font=("Segoe UI", 9)).grid(
        row=2, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 2))
    for i, name in enumerate(have):
        tk.Label(root, text=name, bg=BG, fg=FG, font=("Consolas", 9)).grid(row=3 + i, column=0, sticky="w", padx=14)
        tk.Entry(root, textvariable=have[name], width=64, bg=WELL, fg=FG, insertbackground=FG,
                 relief="flat").grid(row=3 + i, column=1, sticky="we", padx=(6, 6), pady=2)

        def pick(var=have[name], n=name):
            # Windows' own picker, owned by this window, so it opens above
            # this window, which is topmost, rather than under it
            p = filedialog.askopenfilename(title="Where is %s?" % n, filetypes=[(n, n), ("DLL", "*.dll")],
                                           parent=root)
            if p:
                var.set(os.path.normpath(p))

        tk.Button(root, text="Browse", command=pick, relief="flat", bg=RAISED, fg=FG, **PRESSED).grid(
            row=3 + i, column=2, padx=(0, 14))
    tk.Label(root, text="Motion vectors come from ReshadeMotionEstimation by Jakob Wapenhensch (CC BY-NC "
                        "4.0), fetched with the rest.",
             bg=BG, fg=DIM, justify="left", wraplength=620, font=("Segoe UI", 9)).grid(
        row=5, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 2))
    log = tk.Text(root, width=88, height=14, bg=WELL, fg=FG, relief="flat", font=("Consolas", 9),
                  state="disabled", wrap="word")
    log.grid(row=7, column=0, columnspan=3, padx=14, pady=(10, 6), sticky="we")
    status = tk.Label(root, text="", bg=BG, fg=DIM, font=("Segoe UI", 9))
    status.grid(row=8, column=0, columnspan=2, sticky="w", padx=14)
    result = {"ok": False, "done": False}
    q = queue.Queue()

    def append(text):
        log.config(state="normal")
        log.insert("end", text + "\n")
        log.see("end")
        log.config(state="disabled")

    def pump():
        try:
            while True:
                item = q.get_nowait()
                if item is None:
                    result["done"] = True
                    go.config(state="normal", text="Close" if result["ok"] else "Try again")
                    status.config(text="The stack works." if result["ok"] else "Not working yet. See above.",
                                  fg=ACCENT if result["ok"] else WARN)
                    return
                append(item)
        except queue.Empty:
            pass
        root.after(100, pump)

    def work(target, dlssnr, dlss):
        # plain strings only: Tk may be touched from the main thread alone, and
        # at the lens's offer the main thread is in wait_window, not mainloop,
        # so a .get() here raised "main thread is not in main loop"
        try:
            ok = Install(target, dlssnr or None, dlss or None, log=q.put).run()
            result["ok"] = ok
        except StackError as exc:
            q.put("")
            q.put("FAILED: %s" % exc)
        except Exception as exc:
            q.put("")
            q.put("FAILED: %r" % exc)
        q.put(None)

    def start():
        if result["done"] and result["ok"]:
            root.destroy()
            return
        result["done"] = False
        go.config(state="disabled", text="Installing...")
        status.config(text="", fg=DIM)
        threading.Thread(target=work, daemon=True,
                         args=(target, have["nvngx_dlssnr.dll"].get(), have["nvngx_dlss.dll"].get())).start()
        root.after(100, pump)

    go = tk.Button(root, text="Set it up", command=start, relief="flat", bg=ACCENT, fg=WELL,
                   font=("Segoe UI", 10, "bold"), state="normal" if supported else "disabled", **PRESSED)
    go.grid(row=8, column=2, sticky="e", padx=14, pady=(4, 14))
    tk.Button(root, text="Not now", command=root.destroy, relief="flat", bg=RAISED, fg=FG, **PRESSED).grid(
        row=9, column=2, sticky="e", padx=14, pady=(0, 14))
    if shell is not None:
        shell.finish(go, status, log)
    if look is not None:
        # the caption in the look's colours and the window out of the picture
        # while it is unseen, then shown as it always was. Over the lens's offer
        # it is shown on top and not made active, as Tk shows a window it maps.
        # From the Start Menu's entry it is the program's first window, which
        # Tk makes active, so there wm deiconify asks Windows for the keyboard
        root.update_idletasks()
        try:
            look.dress(root)
        except Exception:
            pass                        # shown all the same, in Windows' own caption
        if parent:
            root.state("normal")
        else:
            root.deiconify()
    root.grab_set() if parent else None
    if parent:
        parent.wait_window(root)
    else:
        root.mainloop()
    # the folder it installed into, so a caller can point the lens straight at
    # it; a string is truthy, so callers that only ask whether it worked are fine
    return os.path.abspath(target) if result["ok"] else False


# ---------------------------------------------------------------- entry
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="fetch and assemble the Neural Rendering stack for the lens")
    ap.add_argument("--target", default=DEFAULT_TARGET,
                    help="the folder to install the stack into; installed, the lens's own folder is the "
                         "only one that works, and from source the default is stack, beside the script")
    ap.add_argument("--dlssnr", help="an nvngx_dlssnr.dll you already have; its hash is checked")
    ap.add_argument("--dlss", help="an nvngx_dlss.dll you already have; its hash is checked")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="drme",
                    help="which fetched shader estimates motion vectors (default drme)")
    ap.add_argument("--addon", choices=sorted(ADDON_BUILDS),
                    help="which build of the Neural Rendering add-on to put in place. Without it the setup "
                         "takes the lens's own choice, addon in neural-lens.ini, and 5.2.1 where that has none")
    ap.add_argument("--verify", action="store_true",
                    help="only run the self test, and check that the layer is limited to the lens")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove what the install record lists, and the layer registration")
    a = ap.parse_args(argv)
    try:
        if a.uninstall:
            uninstall(a.target)
            return 0
        if a.verify:
            ok, detail = verify(a.target)
            print(detail)
            ungated = layer_ungated()
            print(layer_line(ungated))
            print(fast_engine_line(a.target))
            return 0 if ok and not ungated else 1
        inst = Install(a.target, a.dlssnr, a.dlss, provider=a.provider)
        inst.addon = a.addon            # None leaves the lens's own choice, see addon_choice
        ok = inst.run()
        print("")
        if not ok:
            print("The stack was installed but the self test did not pass; see above.")
        elif FROZEN or same_path(a.target, DEFAULT_TARGET):
            print("OK: the stack works in %s." % a.target)
        else:
            print("OK: the stack works in %s. Point the lens at it with --stack-dir." % a.target)
        return 0 if ok else 1
    except StackError as exc:
        print("")
        print("FAILED: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
