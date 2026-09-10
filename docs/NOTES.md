# Engineering notes

What was tried and rejected, each with the measurement that killed it, plus the Win32 details
that are easy to get wrong. Worth reading before changing the capture path, because most of
these look reasonable on paper and fail only when measured.

## Dead ends

### Desktop Duplication (ddagrab) under the lens

It cannot see beneath an occluding window, whether or not that window is excluded from
capture, and not even when something is actively repainting underneath it.

```
capture a region away from the lens          YAVG 45.7    real content
capture exactly where the lens sits          YAVG 18.0    black is 16

magnifier repainting that rect, no lens      YAVG 45.96
same, with an excluded lens on top           YAVG 20.04   black again
```

`WDA_EXCLUDEFROMCAPTURE` removes a window from the capture, but it does not make Windows
render the desktop behind it. Nothing composites an occluded region, so the duplication buffer
stays empty there and only transient dirty rects ever land in it. The symptom is a black
viewport that gradually accumulates mouse trails and window drag smears, and that carries
stale content along when the lens is moved.

One earlier test seemed to disprove this and was misleading: a static window over another
static window captures correctly, because DWM still holds both buffers. A Vulkan swapchain
presenting sixty times a second means the region beneath it is never redrawn. Also sample
YAVG rather than chroma; a chroma only check gave a false pass.

### gdigrab or BitBlt of the magnifier window

Blank whether occluded or not. The magnifier composites through DWM, and BitBlt only sees the
window's own GDI surface, which is empty.

### MagSetImageScalingCallback

Deprecated. It is accepted and returns TRUE, and then the next Mag call deadlocks when driven
from ctypes, most likely because the callback takes structures by value. Made unnecessary by
capturing the host window with WGC instead.

### UDP transport

Resyncs badly after a restart: 353 buffering events, with frames arriving every few seconds.
Moot now that nothing restarts. A pipe and TCP both measured 60 fps.

### `--untimed`

The original runaway neural blob. Presents outnumbered frame arrivals, so Neural Rendering
reprocessed its own output roughly sixty times per source frame until the picture collapsed.
Never add it.

### An in-app NR health indicator

Comparing the frame sent to mpv against the frame actually displayed separated NR on from NR
off by only 1.4x (0.58 off, 0.82 on, and 1.7 on in a different scene, so the scene mattered
more than the setting). Whole frame averaging at 1/8 stride washes out exactly the local
detail that Neural Rendering changes. It would have raised false alarms, so it was removed.
The F6 toggle is unambiguous instead, measuring 12.7/255 on plain text.

## Gotchas

- WGC cannot find a `WS_EX_TOOLWINDOW` window. The magnifier host must be a plain popup, and
  it should be captured by `window_hwnd` rather than by name.
- `windows_capture` dispatches handlers by function `__name__`. They must literally be called
  `on_frame_arrived` and `on_closed`, or it raises ValueError.
- `frame.frame_buffer` is row padded and non contiguous (stride 2304 for width 560). Slice
  `[:h, :w, :]` and pass it through `np.ascontiguousarray(...).tobytes()`.
- Passing `HWND_TOPMOST` as Python `-1` through ctypes silently fails on x64, because a 32 bit
  int goes into a pointer parameter. Use `ctypes.c_void_p(-1)`. mpv resets its own z order
  anyway, so give it `--ontop` rather than forcing the z order from outside.
- `MagSetWindowTransform` is optional, and it deadlocks if called after the scaling callback
  has been set. Skip it; the identity transform is the default.
- The lens is deliberately **not** excluded from capture, which is what makes its output
  measurable with ddagrab. That is how see-through was verified: the lens output correlated
  0.997 with ground truth of the region behind it.
- `RegisterHotKey` posts `WM_HOTKEY` to the registering thread's message queue. It has to be
  registered on the same thread that pumps messages, not on a thread whose queue belongs to
  something else such as a tkinter mainloop.
