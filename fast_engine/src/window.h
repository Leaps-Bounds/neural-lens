// window.h: the engine's one window and its swapchain.
//
// The window is a borderless popup that lies over the screen region it shows a rendered
// copy of. It is topmost, it never takes focus, clicks fall through it to whatever lies
// beneath, and with --exclude it is left out of screen captures, the engine's own
// included, so the capture sees the desktop under it and not the lens itself.
//
//   class    "NeuralLensFast". The lens finds the window by process id and this class
//            name, as soon as it is visible.
//   styles   WS_POPUP, and WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE |
//            WS_EX_LAYERED | WS_EX_TRANSPARENT, with SetLayeredWindowAttributes(alpha 255).
//            A tool window that never activates has no taskbar button, and the styles go
//            on at creation, so no button flashes.
//   hidden   It is created hidden. show() makes it visible once the first picture has
//            been presented, so nothing black flashes over the screen.
//
// After that the lens handles the window from its own process: it sets LAYERED,
// TRANSPARENT and NOACTIVATE again, moves it with SetWindowPos, clips it with SetWindowRgn
// (the A/B split) and hides and shows it. Those calls are answered by this window's
// thread, so the main loop has to pump messages promptly: measured with the Vulkan
// presenter, a loop asleep on something else made each move of the lens wait 267 ms.
// The window never changes size: for another size the lens starts another presenter.
//
// The swapchain: B8G8R8A8_UNORM, 2 buffers, DXGI_SWAP_EFFECT_FLIP_DISCARD, made on
// gpu.queue. For a monitor with Windows HDR on it is R16G16B16A16_FLOAT in the scRGB colour
// space instead (desc.hdr, and set_hdr() while it runs), linear with 1.0 at 80 nits, which
// is how the desktop of such a monitor is composed: the picture is then shown in HDR as the
// desktop is, and not at the SDR white level as a standard range picture would be. Two
// ways to make it, chosen by --present, because whether a layered window takes a flip model
// swapchain directly is only known on screen:
//   Hwnd   CreateSwapChainForHwnd
//   Dcomp  CreateSwapChainForComposition, shown through a DirectComposition visual on a
//          target for the window
// Both are complete. Everything else in this file behaves the same for either. When Hwnd
// is asked for and the window refuses the swapchain, Dcomp is tried before create() gives
// up, and a note on stderr names the one in use. Dcomp asked for outright is never
// replaced, so a log says plainly whether it works.
//
// Threads: the main thread only, which is also the thread that created the window.
#pragma once

#include "common.h"
#include "gpu.h"
#include "pipeline.h"  // Target

// What DXGI's frame statistics say of the swapchain: which present the display showed last,
// and at which refresh. All of it is the system's own account, read without waiting.
struct PresentShown {
  UINT id = 0;            // the present shown, in the numbers Window::present_id() gives
  UINT refresh = 0;       // the count of the refresh that first showed it
  UINT sync_refresh = 0;  // the count of the refresh the statistics were taken at
  double sync_s = 0.0;    // the moment of that refresh, on now_s()'s clock
};

// One frame of the desktop compositor, from its own statistics, on now_s()'s clock.
struct CompositorFrame {
  static constexpr int kTargets = 4;
  UINT64 id = 0;
  double start_s = 0.0;    // when the compositor began the frame
  double target_s = 0.0;   // the refresh it composed the frame for
  double period_s = 0.0;   // the compositor's own period
  int targets = 0;         // the displays the frame went to, kTargets at most
  struct Target {
    UINT source = 0;        // the display's source number on its adapter
    double present_s = 0.0; // when the compositor presented to it, 0 when it did not
    double shown_s = 0.0;   // the refresh that showed it, 0 when none is known
    UINT refresh = 0;       // that refresh's count on its display
    double vblank_s = 0.0;  // that display's time from one refresh to the next
  } target[kTargets];
};

struct WindowDesc {
  int x = 0;           // --at, physical pixels in virtual screen coordinates
  int y = 0;
  int width = 0;       // --size, the client area, the swapchain's buffers and the picture
  int height = 0;
  std::wstring title;  // --title
  bool exclude = false;                  // --exclude: SetWindowDisplayAffinity(0x11)
  PresentPath path = PresentPath::Hwnd;  // --present
  bool hdr = false;                      // the swapchain in 16-bit floats, scRGB, see kHdrFormat
};

class Window {
 public:
  static constexpr const wchar_t* kClassName = L"NeuralLensFast";
  static constexpr DXGI_FORMAT kFormat = DXGI_FORMAT_B8G8R8A8_UNORM;  // 87 in the ready line
  // With Windows HDR on for the monitor: 10 in the ready line, and the colour space is
  // DXGI_COLOR_SPACE_RGB_FULL_G10_NONE_P709, scRGB.
  static constexpr DXGI_FORMAT kHdrFormat = DXGI_FORMAT_R16G16B16A16_FLOAT;
  static constexpr UINT kBuffers = 2;                                 // "2 images"

  Window();
  ~Window();  // calls destroy()
  Window(const Window&) = delete;
  Window& operator=(const Window&) = delete;

  // Registers the class, creates the window hidden with the styles above at desc's place
  // and size, applies the capture exclusion, and creates the swapchain and a render target
  // view for each of its buffers. set_dpi_aware() has been called before. gpu must outlive
  // the window.
  // false with err: the step and its code, "CreateSwapChainForHwnd failed 0x887A0001" for
  // one, so that a log tells whether to try the other --present path. After a failure
  // nothing is left behind.
  // A capture exclusion that Windows refuses is such a failure too, not a note: seen by
  // its own capture, the engine would take its own output for a new frame for ever.
  // With desc.hdr the swapchain is made in kHdrFormat and put in the scRGB colour space.
  // A swapchain that does not take that colour space is not a failure: a note says so and
  // the swapchain is made in kFormat, hdr() then says false.
  bool create(Gpu& gpu, const WindowDesc& desc, std::string& err);

  // The window, null before create() and after destroy().
  HWND hwnd() const;

  // Whether the swapchain is in kHdrFormat and scRGB, and its format, kFormat or kHdrFormat.
  bool hdr() const;
  DXGI_FORMAT format() const;

  // Makes the swapchain's buffers again in the other format, kHdrFormat and scRGB with on,
  // kFormat without, in place: the window and the swapchain stay, the buffers and their
  // views are new, and whatever the buffers held is gone, so the caller presents a picture
  // next. The caller has waited for the GPU first (Gpu::flush), and holds no Target from
  // back_buffer(). Nothing happens when the swapchain is in that format already. As with
  // create(), a colour space the swapchain does not take leaves it in kFormat with a note.
  // false with err when the buffers could not be made again: the swapchain is then not to
  // be used, and the caller leaves as after a lost device.
  bool set_hdr(bool on, std::string& err);

  // The buffer the next present() will show, as something to draw into: its texture, a
  // render target view, the size and the format. The texture is in PRESENT and must be
  // back in PRESENT before present(). With FLIP_DISCARD its old content is undefined: the
  // pipeline writes every texel. The pointers are the window's and stay valid until
  // destroy() or set_hdr().
  // false with err after destroy() or a lost device.
  bool back_buffer(Target& out, std::string& err);

  // Presents the current back buffer: Present(0, 0). With the flip model and interval 0
  // the call does not wait for the display, and the compositor shows the newest picture.
  // The draw into the buffer need not be finished: the present is queued behind it.
  // DXGI_STATUS_OCCLUDED is not an error, the call returns true; it is what a hidden or
  // covered window gets.
  // false with err only when the swapchain can no longer present: "device removed 0x..."
  // with the device's reason, "device reset", or another failure code. The caller prints
  // "engine failed REASON" and leaves.
  bool present(std::string& err);

  // The number of the present just made, which the frame statistics name it by later
  // (GetLastPresentCount). 0 when it cannot be read.
  UINT present_id() const;

  // Which present the display showed last and when (GetFrameStatistics). The moment a
  // present was shown is sync_s + (refresh - sync_refresh) refresh periods. It answers for
  // the newest present shown only, so whoever wants every present asks at least once a
  // refresh. false when there is nothing to report: before the first picture is on screen,
  // and once after any break in the display's counting, as after a change of mode.
  bool shown(PresentShown& out) const;

  // The desktop compositor's frames completed since the last call, oldest first, the newest
  // 64 at most, appended to out. The numbers are its own: when it began each frame, which
  // refresh it composed it for, and when each display showed it. false where the system
  // keeps no such statistics (before Windows 11). It is not bound to this window. Main
  // thread.
  static bool compositor_frames(std::vector<CompositorFrame>& out);

  // Shows the window without activating it (SW_SHOWNA). The loop calls it once, right
  // after the first present, and then presents again: whether a picture presented while
  // hidden is on screen at the moment of showing is not something to rely on.
  void show();

  // Handles every message waiting for this thread and returns. Call it whenever the loop
  // wakes, and wait with MsgWaitForMultipleObjects(..., QS_ALLINPUT) so that a message
  // wakes it. It returns false once the window has been closed or destroyed from outside
  // (WM_CLOSE, WM_DESTROY, WM_QUIT, and the end of the Windows session): the loop then
  // leaves. The window is not destroyed by a close, destroy() does that. Keys the lens
  // posts for ReShade's sake are swallowed, and so is every system command that would
  // start a loop of the system's own (move, size, menu).
  bool pump();

  // What pump() is doing at this moment, in words: the message being dispatched and the
  // class of the window it is for, how many the running call has taken, and the message
  // this window's own procedure is in. Any thread may ask: the watchdog says it when it
  // gives up on a loop stuck in pump(), which otherwise leaves no trace.
  static std::string pump_state();

  // The refresh rate of the monitor the window's middle is on, 60 when it cannot be read.
  // Read afresh on each call, so it follows a change of the display's mode. It sets the
  // wait of the busy states and feeds capture_interval_ms(). A call costs about 2
  // microseconds (measured), so it may be asked every turn.
  double refresh_hz() const;

  // Releases the swapchain and destroys the window. The caller has waited for the GPU
  // first (Gpu::flush): nothing submitted may still draw into a back buffer. Safe to call
  // twice and without create.
  void destroy();

 private:
  struct Impl;
  Impl* impl_ = nullptr;
};
