"""The lens's presenter: each captured frame goes straight into a Vulkan swapchain.

No player, no clock, no buffer. A frame arrives from Windows Graphics Capture,
is copied into a staging buffer, from there into the next swapchain image, and
presented; a frame that arrives before the loop gets to the previous one
replaces it. Between arrivals the last frame is presented again at the
display's rate, copied in afresh each time, so Neural Rendering always works
on the original and never on its own output, which is what made mpv's
--untimed collapse. ReShade's Vulkan layer, the Feed and the Neural Rendering
add-on attach to this swapchain as they do to mpv's: the process is the stack
folder's own lens-presenter.exe, on the layer's allow list, started with the
stack folder as its working directory so the same ReShade.ini is found.

Measured on an RTX 5090 with a 120 Hz display, from a change on screen to the
change in this window, both read through the compositor: 8 ms, one refresh,
against 70 ms through mpv at 99 fps.

    lens-presenter.exe lens_presenter.py --source window:<hwnd> | monitor:<index>
        --at X Y --size W H [--crop X Y] [--title T] [--exclude] [--fifo]

--crop is for monitor capture: where in the monitor the shown region starts.
--exclude marks the window WDA_EXCLUDEFROMCAPTURE, so a monitor capture does
not see the presenter itself where it lies over the captured region.

Lines on stdin:
    crop X Y        move the captured region (monitor capture)
    shot BASE       save BASE-before.png (the captured frame), BASE-after.png (the
                    last presented output, read back from the swapchain) and
                    BASE-side-by-side.png, then print "shot done"
    quit            leave

Lines on stdout, once a second:
    stats new=N arrived=N repeated=N dropped=N meter=MS
where meter is the median, over that second, of the present call minus the
capture's own timestamp for frames presented for the first time. The timestamp
is the composition the frame belongs to, so this can be slightly negative.
"""
import argparse
import ctypes
import os
import struct
import sys
import threading
import time
import zlib

import numpy as np
import glfw
import vulkan as vk
from windows_capture import WindowsCapture

ap = argparse.ArgumentParser()
ap.add_argument("--source", required=True)
ap.add_argument("--at", nargs=2, type=int, required=True)
ap.add_argument("--size", nargs=2, type=int, required=True)
ap.add_argument("--crop", nargs=2, type=int, default=[0, 0])
ap.add_argument("--title", default="LensPresenter")
ap.add_argument("--exclude", action="store_true")
ap.add_argument("--fifo", action="store_true")
args = ap.parse_args()
X, Y = args.at
W, H = args.size
u = ctypes.windll.user32
u.SetProcessDPIAware()


def say(text):
    print(text, flush=True)


# ---- window
if not glfw.init():
    sys.exit("glfw init failed")
glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
glfw.window_hint(glfw.DECORATED, glfw.FALSE)
glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
glfw.window_hint(glfw.FLOATING, glfw.TRUE)
glfw.window_hint(glfw.FOCUS_ON_SHOW, glfw.FALSE)
win = glfw.create_window(W, H, args.title, None, None)
glfw.set_window_pos(win, X, Y)
hwnd = glfw.get_win32_window(win)
if args.exclude:
    u.SetWindowDisplayAffinity(hwnd, 0x11)
glfw.poll_events()

# ---- vulkan
ffi = vk.ffi
instance = vk.vkCreateInstance(vk.VkInstanceCreateInfo(
    sType=vk.VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
    pApplicationInfo=vk.VkApplicationInfo(sType=vk.VK_STRUCTURE_TYPE_APPLICATION_INFO,
                                          pApplicationName="lens presenter", applicationVersion=1,
                                          pEngineName="none", engineVersion=1,
                                          apiVersion=vk.VK_MAKE_VERSION(1, 1, 0)),
    enabledExtensionCount=2, ppEnabledExtensionNames=["VK_KHR_surface", "VK_KHR_win32_surface"],
    enabledLayerCount=0), None)


def iproc(name):
    return vk.vkGetInstanceProcAddr(instance, name)


hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
surface = iproc("vkCreateWin32SurfaceKHR")(instance, vk.VkWin32SurfaceCreateInfoKHR(
    sType=vk.VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR,
    hinstance=ffi.cast("void*", hinst), hwnd=ffi.cast("void*", hwnd)), None)
phys = vk.vkEnumeratePhysicalDevices(instance)[0]
props = vk.vkGetPhysicalDeviceProperties(phys)
support = iproc("vkGetPhysicalDeviceSurfaceSupportKHR")
qi = next(i for i, q in enumerate(vk.vkGetPhysicalDeviceQueueFamilyProperties(phys))
          if q.queueFlags & vk.VK_QUEUE_GRAPHICS_BIT and support(phys, i, surface))
device = vk.vkCreateDevice(phys, vk.VkDeviceCreateInfo(
    sType=vk.VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, queueCreateInfoCount=1,
    pQueueCreateInfos=[vk.VkDeviceQueueCreateInfo(sType=vk.VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                                   queueFamilyIndex=qi, queueCount=1, pQueuePriorities=[1.0])],
    enabledExtensionCount=1, ppEnabledExtensionNames=["VK_KHR_swapchain"], enabledLayerCount=0), None)
queue = vk.vkGetDeviceQueue(device, qi, 0)


def dproc(name):
    return vk.vkGetDeviceProcAddr(device, name)


caps = iproc("vkGetPhysicalDeviceSurfaceCapabilitiesKHR")(phys, surface)
formats = iproc("vkGetPhysicalDeviceSurfaceFormatsKHR")(phys, surface)
modes = iproc("vkGetPhysicalDeviceSurfacePresentModesKHR")(phys, surface)
# The captured frames are 8 bit BGRA and go into an 8 bit swapchain by a straight copy.
# mpv presents through a 10 bit swapchain; with LENS_PRESENTER_10BIT=1 so does this, the
# frames converted on the GPU by a blit through an intermediate image. Measured, it made
# no difference to Neural Rendering's effect and cost frame rate, 91 against 118.
want_fmt = vk.VK_FORMAT_A2B10G10R10_UNORM_PACK32 if os.environ.get("LENS_PRESENTER_10BIT") else vk.VK_FORMAT_B8G8R8A8_UNORM
fmt = next((f for f in formats if f.format == want_fmt),
           next((f for f in formats if f.format == vk.VK_FORMAT_B8G8R8A8_UNORM), formats[0]))
direct = fmt.format == vk.VK_FORMAT_B8G8R8A8_UNORM
mode = vk.VK_PRESENT_MODE_FIFO_KHR
if not args.fifo and vk.VK_PRESENT_MODE_MAILBOX_KHR in modes:
    mode = vk.VK_PRESENT_MODE_MAILBOX_KHR
count = max(caps.minImageCount, 2)
if caps.maxImageCount:
    count = min(count, caps.maxImageCount)
usage = vk.VK_IMAGE_USAGE_TRANSFER_DST_BIT | vk.VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT
readback_ok = bool(caps.supportedUsageFlags & vk.VK_IMAGE_USAGE_TRANSFER_SRC_BIT)
if readback_ok:
    usage |= vk.VK_IMAGE_USAGE_TRANSFER_SRC_BIT
swapchain = dproc("vkCreateSwapchainKHR")(device, vk.VkSwapchainCreateInfoKHR(
    sType=vk.VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, surface=surface, minImageCount=count,
    imageFormat=fmt.format, imageColorSpace=fmt.colorSpace, imageExtent=vk.VkExtent2D(width=W, height=H),
    imageArrayLayers=1, imageUsage=usage, imageSharingMode=vk.VK_SHARING_MODE_EXCLUSIVE,
    preTransform=caps.currentTransform, compositeAlpha=vk.VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR,
    presentMode=mode, clipped=vk.VK_TRUE), None)
images = dproc("vkGetSwapchainImagesKHR")(device, swapchain)
acquire = dproc("vkAcquireNextImageKHR")
present = dproc("vkQueuePresentKHR")
presented = [False] * len(images)        # whether each image holds a presented picture

size = W * H * 4
mprops = vk.vkGetPhysicalDeviceMemoryProperties(phys)


def host_buffer(flags):
    b = vk.vkCreateBuffer(device, vk.VkBufferCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, size=size, usage=flags,
        sharingMode=vk.VK_SHARING_MODE_EXCLUSIVE), None)
    req = vk.vkGetBufferMemoryRequirements(device, b)
    want = vk.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | vk.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
    mt = next(i for i in range(mprops.memoryTypeCount)
              if req.memoryTypeBits & (1 << i) and (mprops.memoryTypes[i].propertyFlags & want) == want)
    m = vk.vkAllocateMemory(device, vk.VkMemoryAllocateInfo(
        sType=vk.VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, allocationSize=req.size, memoryTypeIndex=mt), None)
    vk.vkBindBufferMemory(device, b, m, 0)
    view = np.frombuffer(vk.vkMapMemory(device, m, 0, size, 0), dtype=np.uint8, count=size).reshape(H, W, 4)
    return b, view


buf, staging = host_buffer(vk.VK_BUFFER_USAGE_TRANSFER_SRC_BIT)
mid = None
if not direct:
    mid = vk.vkCreateImage(device, vk.VkImageCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, imageType=vk.VK_IMAGE_TYPE_2D,
        format=vk.VK_FORMAT_B8G8R8A8_UNORM, extent=vk.VkExtent3D(width=W, height=H, depth=1),
        mipLevels=1, arrayLayers=1, samples=vk.VK_SAMPLE_COUNT_1_BIT, tiling=vk.VK_IMAGE_TILING_OPTIMAL,
        usage=vk.VK_IMAGE_USAGE_TRANSFER_SRC_BIT | vk.VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        sharingMode=vk.VK_SHARING_MODE_EXCLUSIVE, initialLayout=vk.VK_IMAGE_LAYOUT_UNDEFINED), None)
    mreq = vk.vkGetImageMemoryRequirements(device, mid)
    mt = next(i for i in range(mprops.memoryTypeCount)
              if mreq.memoryTypeBits & (1 << i)
              and mprops.memoryTypes[i].propertyFlags & vk.VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)
    mmem = vk.vkAllocateMemory(device, vk.VkMemoryAllocateInfo(
        sType=vk.VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, allocationSize=mreq.size, memoryTypeIndex=mt), None)
    vk.vkBindImageMemory(device, mid, mmem, 0)
rbuf, readback = host_buffer(vk.VK_BUFFER_USAGE_TRANSFER_DST_BIT) if readback_ok else (None, None)

pool = vk.vkCreateCommandPool(device, vk.VkCommandPoolCreateInfo(
    sType=vk.VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, queueFamilyIndex=qi,
    flags=vk.VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT), None)
cmds = vk.vkAllocateCommandBuffers(device, vk.VkCommandBufferAllocateInfo(
    sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, commandPool=pool,
    level=vk.VK_COMMAND_BUFFER_LEVEL_PRIMARY, commandBufferCount=len(images)))
sem_acquire = vk.vkCreateSemaphore(device, vk.VkSemaphoreCreateInfo(sType=vk.VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO), None)
sem_done = vk.vkCreateSemaphore(device, vk.VkSemaphoreCreateInfo(sType=vk.VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO), None)
fence = vk.vkCreateFence(device, vk.VkFenceCreateInfo(sType=vk.VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
                                                       flags=vk.VK_FENCE_CREATE_SIGNALED_BIT), None)
sub = vk.VkImageSubresourceRange(aspectMask=vk.VK_IMAGE_ASPECT_COLOR_BIT, baseMipLevel=0, levelCount=1,
                                 baseArrayLayer=0, layerCount=1)
layers = vk.VkImageSubresourceLayers(aspectMask=vk.VK_IMAGE_ASPECT_COLOR_BIT, mipLevel=0, baseArrayLayer=0,
                                     layerCount=1)
region = vk.VkBufferImageCopy(bufferOffset=0, bufferRowLength=0, bufferImageHeight=0, imageSubresource=layers,
                              imageOffset=vk.VkOffset3D(x=0, y=0, z=0),
                              imageExtent=vk.VkExtent3D(width=W, height=H, depth=1))


def barrier(cmd, image, old, new, src_access, dst_access, src_stage, dst_stage):
    b = vk.VkImageMemoryBarrier(sType=vk.VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, srcAccessMask=src_access,
                                dstAccessMask=dst_access, oldLayout=old, newLayout=new,
                                srcQueueFamilyIndex=vk.VK_QUEUE_FAMILY_IGNORED,
                                dstQueueFamilyIndex=vk.VK_QUEUE_FAMILY_IGNORED, image=image, subresourceRange=sub)
    vk.vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, None, 0, None, 1, [b])


def record(cmd, idx, read_back):
    """Copy the staging buffer into swapchain image idx, reading the picture it
    still holds from its last present back out first when a screenshot wants it."""
    image = images[idx]
    vk.vkBeginCommandBuffer(cmd, vk.VkCommandBufferBeginInfo(
        sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, flags=vk.VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT))
    if read_back and presented[idx]:
        barrier(cmd, image, vk.VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, vk.VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                0, vk.VK_ACCESS_TRANSFER_READ_BIT, vk.VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                vk.VK_PIPELINE_STAGE_TRANSFER_BIT)
        vk.vkCmdCopyImageToBuffer(cmd, image, vk.VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, rbuf, 1, [region])
        barrier(cmd, image, vk.VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                vk.VK_ACCESS_TRANSFER_READ_BIT, vk.VK_ACCESS_TRANSFER_WRITE_BIT,
                vk.VK_PIPELINE_STAGE_TRANSFER_BIT, vk.VK_PIPELINE_STAGE_TRANSFER_BIT)
    else:
        barrier(cmd, image, vk.VK_IMAGE_LAYOUT_UNDEFINED, vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                0, vk.VK_ACCESS_TRANSFER_WRITE_BIT, vk.VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                vk.VK_PIPELINE_STAGE_TRANSFER_BIT)
    if mid is None:
        vk.vkCmdCopyBufferToImage(cmd, buf, image, vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, [region])
    else:
        barrier(cmd, mid, vk.VK_IMAGE_LAYOUT_UNDEFINED, vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                0, vk.VK_ACCESS_TRANSFER_WRITE_BIT, vk.VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                vk.VK_PIPELINE_STAGE_TRANSFER_BIT)
        vk.vkCmdCopyBufferToImage(cmd, buf, mid, vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, [region])
        barrier(cmd, mid, vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, vk.VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                vk.VK_ACCESS_TRANSFER_WRITE_BIT, vk.VK_ACCESS_TRANSFER_READ_BIT,
                vk.VK_PIPELINE_STAGE_TRANSFER_BIT, vk.VK_PIPELINE_STAGE_TRANSFER_BIT)
        blit = vk.VkImageBlit(srcSubresource=layers, srcOffsets=[vk.VkOffset3D(x=0, y=0, z=0), vk.VkOffset3D(x=W, y=H, z=1)],
                              dstSubresource=layers, dstOffsets=[vk.VkOffset3D(x=0, y=0, z=0), vk.VkOffset3D(x=W, y=H, z=1)])
        vk.vkCmdBlitImage(cmd, mid, vk.VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, image,
                          vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, [blit], vk.VK_FILTER_NEAREST)
    barrier(cmd, image, vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, vk.VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,
            vk.VK_ACCESS_TRANSFER_WRITE_BIT, 0, vk.VK_PIPELINE_STAGE_TRANSFER_BIT,
            vk.VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT)
    vk.vkEndCommandBuffer(cmd)


# ---- capture: one slot, the newest frame wins
slot = {"frame": np.empty((H, W, 4), np.uint8), "spare": np.empty((H, W, 4), np.uint8),
        "ts": 0.0, "new": False, "dropped": 0, "arrived": 0}
crop = {"x": args.crop[0], "y": args.crop[1]}
cv = threading.Condition()
kind, ref = args.source.split(":", 1)
if kind == "window":
    cap = WindowsCapture(cursor_capture=False, draw_border=False, minimum_update_interval=0,
                         window_hwnd=int(ref))
else:
    cap = WindowsCapture(cursor_capture=False, draw_border=False, minimum_update_interval=0,
                         monitor_index=int(ref))


def on_frame_arrived(frame, control):
    try:
        cx, cy = (crop["x"], crop["y"]) if kind == "monitor" else (0, 0)
        cx = max(0, min(cx, frame.width - W))
        cy = max(0, min(cy, frame.height - H))
        if frame.height < H or frame.width < W:
            return
        with cv:
            np.copyto(slot["spare"], frame.frame_buffer[cy:cy + H, cx:cx + W, :])
            slot["frame"], slot["spare"] = slot["spare"], slot["frame"]
            slot["ts"] = frame.timespan / 1e7
            if slot["new"]:
                slot["dropped"] += 1
            slot["new"] = True
            slot["arrived"] += 1
            cv.notify()
    except Exception:
        pass


def on_closed():
    pass


cap.event(on_frame_arrived)
cap.event(on_closed)
ctl = cap.start_free_threaded()

# ---- commands on stdin
wanted = {"quit": False, "shot": None}


def commands():
    for line in sys.stdin:
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "quit":
            wanted["quit"] = True
            return
        if parts[0] == "crop" and len(parts) == 3:
            try:
                crop["x"], crop["y"] = int(parts[1]), int(parts[2])
            except ValueError:
                pass
        elif parts[0] == "shot" and len(parts) >= 2:
            wanted["shot"] = line.strip()[5:]
    wanted["quit"] = True


threading.Thread(target=commands, daemon=True).start()


def write_png(path, rgb):
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + rgb[r].tobytes() for r in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def bgra_to_rgb(a):
    return np.ascontiguousarray(a[:, :, 2::-1])


def readback_rgb():
    """The read back swapchain image as RGB8, whatever the swapchain's format."""
    if direct:
        return bgra_to_rgb(readback.copy())
    v = readback.copy().view(np.uint32).reshape(H, W)      # A2 B10 G10 R10, R in the low bits
    return np.dstack([((v & 0x3FF) >> 2).astype(np.uint8), (((v >> 10) & 0x3FF) >> 2).astype(np.uint8),
                      (((v >> 20) & 0x3FF) >> 2).astype(np.uint8)])


say("presenter ready %dx%d at (%d,%d) on %s, format %d, present mode %s, %d images, readback %s, source %s"
    % (W, H, X, Y, props.deviceName, fmt.format, "mailbox" if mode == vk.VK_PRESENT_MODE_MAILBOX_KHR else "fifo",
       len(images), "yes" if readback_ok else "no", args.source))

# ---- the loop
mon = glfw.get_primary_monitor()
vm = glfw.get_video_mode(mon)
refresh = 1.0 / float(vm.refresh_rate if vm and vm.refresh_rate else 60)
lat, new, again, t_report, have = [], 0, 0, time.perf_counter(), False
while not glfw.window_should_close(win) and not wanted["quit"]:
    glfw.poll_events()
    with cv:
        if not slot["new"]:
            cv.wait(refresh)
        fresh = slot["new"]
        if fresh:
            frame, ts = slot["frame"], slot["ts"]
            slot["new"] = False
            vk.vkWaitForFences(device, 1, [fence], vk.VK_TRUE, 10 ** 9)   # the last copy has read the staging buffer
            np.copyto(staging, frame)
            have = True
    if not have:
        continue
    if not fresh:
        vk.vkWaitForFences(device, 1, [fence], vk.VK_TRUE, 10 ** 9)
    shot = wanted["shot"]
    if shot:
        before = bgra_to_rgb(staging.copy())
    vk.vkResetFences(device, 1, [fence])
    idx = acquire(device, swapchain, 10 ** 9, sem_acquire, None)
    record(cmds[idx], idx, bool(shot) and readback_ok)
    vk.vkQueueSubmit(queue, 1, [vk.VkSubmitInfo(
        sType=vk.VK_STRUCTURE_TYPE_SUBMIT_INFO, waitSemaphoreCount=1, pWaitSemaphores=[sem_acquire],
        pWaitDstStageMask=[vk.VK_PIPELINE_STAGE_TRANSFER_BIT], commandBufferCount=1,
        pCommandBuffers=[cmds[idx]], signalSemaphoreCount=1, pSignalSemaphores=[sem_done])], fence)
    present(queue, vk.VkPresentInfoKHR(sType=vk.VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, waitSemaphoreCount=1,
                                       pWaitSemaphores=[sem_done], swapchainCount=1,
                                       pSwapchains=[swapchain], pImageIndices=[idx]))
    had_picture = presented[idx]
    presented[idx] = True
    if fresh:
        lat.append((time.perf_counter() - ts) * 1000.0)
        new += 1
    else:
        again += 1
    if shot:
        wanted["shot"] = None
        try:
            saved = []
            write_png(shot + "-before.png", before)
            saved.append("before")
            if readback_ok and had_picture:
                vk.vkWaitForFences(device, 1, [fence], vk.VK_TRUE, 10 ** 9)
                after = readback_rgb()
                write_png(shot + "-after.png", after)
                saved.append("after")
                write_png(shot + "-side-by-side.png",
                          np.hstack([before, np.full((H, 8, 3), 90, np.uint8), after]))
                saved.append("side by side")
            say("shot done " + ", ".join(saved))
        except Exception as exc:
            say("shot failed %s" % exc)
    now = time.perf_counter()
    if now - t_report >= 1.0:
        h = sorted(lat)
        med = h[len(h) // 2] if h else float("nan")
        say("stats new=%d arrived=%d repeated=%d dropped=%d meter=%.1f" % (new, slot["arrived"], again, slot["dropped"], med))
        lat, new, again, t_report = [], 0, 0, now
        slot["arrived"] = 0
        slot["dropped"] = 0

vk.vkDeviceWaitIdle(device)
