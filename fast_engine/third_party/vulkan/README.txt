The Vulkan headers of The Khronos Group, which the fast engine is compiled with to reach the
card's optical flow unit through Vulkan.

They come from the KhronosGroup/Vulkan-Headers repository on GitHub, tag v1.4.366, commit
73814d006638aa00bd553215b054f0f02e457e22, in the archive
https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/v1.4.366.zip whose sha256 is
7f0adb665a7a5ee67c8720d0e73e76fa9b66390c671cde7999162b8d050432b7.

These files are the archive's, byte for byte and unchanged:
- include/vulkan/vulkan.h, vk_platform.h, vulkan_core.h and vulkan_win32.h
- include/vk_video/*.h, the twelve video headers that vulkan_core.h includes
- LICENSE.md, LICENSES/Apache-2.0.txt and LICENSES/MIT.txt

They are under the Apache 2.0 or MIT licence, as LICENSE.md and the SPDX line of each header
say. The .gitattributes beside this file keeps git from changing their line ends.
