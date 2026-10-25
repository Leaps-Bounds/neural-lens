// model_motion.h: when the network is handed the card's motion estimate as its motion vectors,
// and when zero vectors. The loop (main.cpp), the sequence mode (selftest.cpp) and the
// engine's own print of the cases (--motion-cases) go by these few lines, so the three
// cannot differ. No includes, like look_settings.h.
//
// The model is temporal: at each evaluate it takes the frame it last evaluated as its history
// and reads that history where the motion vectors say each texel's content was. Zero vectors
// say nothing moved, which is right for a still picture and wrong for everything that moves,
// where the history is read from the wrong place and fine detail boils. The card's estimate
// (framegen.h) holds, for each 8x8 block of a new frame, where its content was in the frame
// before. It is the model's own convention, previous minus current, x right, y down, so the
// pipeline hands it over unflipped, in work texels, see Pipeline::set_model_motion and
// shaders\mvec_cs.hlsl.
//
// It is handed over only when it describes the motion from the frame the network last
// evaluated to the frame it evaluates now. Every other render gets zero vectors, as every
// render did before:
//   - a render that resets the network (the first one, a pause, a new work size, a settings
//     change that resets): it has no history to read, and zeros keep it as it always was
//   - the first new frame after FrameGen::forget() or a new target format: no estimate yet
//   - a settle or an again run: the same frame once more, so nothing moved since the last run
//   - a failed estimate, and the frame after it, whose estimate then spans two frames
//   - a frame drawn while the network did not run, or while nothing wanted the estimate, so
//     that the estimate and the network's history start from different frames
//   - a joined draw (LENS_FAST_JOIN, a test switch), whose conversion for the estimate is
//     submitted before its list waits for the capture's copy
//   - in the shared mode, passes 2 and up, whose history is the same frame's pass before
//   - NRMotionSource at 0, and a card without a motion estimator
#pragma once

// Whether the motion estimator runs for a new frame: frame generation is on, the Look stage's
// filter follows the motion, or the network is to be handed it (model_wants: NRMotionSource
// says the card's estimate and the network runs).
inline bool motion_wanted(int framegen, bool look_wants, bool model_wants) {
  return framegen > 0 || look_wants || model_wants;
}

// Which frames the last estimate lies between, and which frame the network last evaluated.
// Frames are numbered by serial, one up for every new frame, as the loop draws it.
struct MotionPair {
  unsigned long long serial = 0;    // the frame being drawn
  unsigned long long est_last = 0;  // the frame the estimator last converted, 0 unknown
  unsigned long long est_from = 0;  // the frames the estimate for this frame lies between,
  unsigned long long est_to = 0;    // 0 when this frame has none
  unsigned long long nr_hist = 0;   // the frame the network last evaluated, 0 none

  // A new frame is about to be drawn, as new or joined.
  void new_frame() {
    ++serial;
    est_from = est_to = 0;
  }
  // FrameGen::estimate() for this frame: ok false when it failed, ready true when it
  // estimated the motion from the frame it converted before.
  void estimated(bool ok, bool ready) {
    if (!ok) {
      est_last = 0;
      return;
    }
    if (ready) {
      est_from = est_last;
      est_to = serial;
    }
    est_last = serial;
  }
  // This frame's estimate starts from the frame the network last evaluated.
  bool pair_ok() const { return est_to == serial && est_from != 0 && est_from == nr_hist; }
  // A draw has been made of the frame being drawn, the network run in it or not: new,
  // joined, settle and again alike, since all of them run on this frame.
  void drew(bool ran_network) {
    if (ran_network) nr_hist = serial;
  }
};

// Whether this frame's render hands the network the estimate. A render that resets the
// network gets zeros all the same, which the pipeline decides, since it knows its own resets.
inline bool feed_model(const MotionPair& pair, bool model_wants, bool joined, bool ready) {
  return model_wants && !joined && ready && pair.pair_ok();
}
