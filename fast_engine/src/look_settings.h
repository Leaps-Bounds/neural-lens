// look_settings.h: the Look stage's settings, as the add-on names them in ReShade.ini's
// [RenoDX.DLSS5] section, so one set of values serves the ReShade engine's add-on in a
// window and the fast engine fullscreen alike, and profiles carry them as they carry every
// key of that section. See look.h for what each does. No includes, so that common.h and
// look.h can both hold it.
#pragma once

// Where the motion vectors the model is handed come from, NRMotionSource in the same section:
// the fast engine's own key, like NRKeepBlacks, which neither build of the add-on reads. A
// number, as the section's other choices are: a value with a fraction is cut to a whole number
// (0.9 is 0), and anything but these two, or no number at all, is the default.
constexpr int kMotionNone = 0;  // zero vectors, which is what the engine handed the model before
constexpr int kMotionCard = 1;  // the card's own motion estimate, see framegen.h and model_motion.h
// Card is the default. It gives the fast engine's network motion vectors, as the Feed gives the
// ReShade engine's in a window, and brings a moving picture nearer the network's own picture at
// rest. None hands it zero vectors, as every version before 0.9.1 did, for a picture where the
// card's estimate softens fine detail in motion, marks the edges of things that move against
// their background or, where the work size is much smaller than the picture, boils more. See
// docs/NOTES.md, Motion vectors for the network. The lens's LOOK_DEFAULTS says the same.
constexpr int kMotionSourceDefault = kMotionCard;

struct NrLook {
  float tone = 1.0f;             // NRLookTone, 0 to 2: the broad band's gain
  float detail = 1.0f;           // NRLookDetail, 0 to 2: the fine band's gain
  float detail_radius = 1.0f;    // NRLookDetailRadius, 0.25 to 4: where broad ends and fine
                                 // begins, as a percent of the work height
  float halo = 0.0f;             // NRLookHalo, 0 to 1: halo suppression
  float halo_bright = 0.0f;      // NRLookHaloBrightSide, 0 to 1: its twin on the bright side of dark things
  int stabilize = 0;             // NRLookStabilize: 0 off, 1 in place, 2 along the motion
  float stabilize_ms = 60.0f;    // NRLookStabilizeMs, 10 to 250: the stabiliser's time
  bool stabilize_detail = false; // NRLookStabilizeDetail: the fine band filtered too
  int detail_stability = 1;      // NRDetailStability: 0 auto (on here), 1 off, 2 always. The
                                 // key missing reads as 1 in the engine, so a stack without
                                 // it draws the picture it always drew
  int keep_blacks = 0;           // NRKeepBlacks: 1 keeps a pixel that is pure black as it is.
                                 // Not the stage's own work: the composite fades the network's
                                 // change to nothing where the native pixel's brightest channel
                                 // is at level 0, and lets it through whole from level 3 up
                                 // (composite_ps.hlsl), since the model lifts such pixels by a
                                 // level or two and nothing else there. Read always, like
                                 // detail stability
  int motion_source = kMotionSourceDefault;  // NRMotionSource: kMotionNone or kMotionCard, see above.
                                 // Not the stage's own work either: it is what the network
                                 // itself is told of the motion, so none of the four tests
                                 // below looks at it and look= on the stats line does not change with
                                 // it. Read always, like detail stability
  float max_brighten = 0.0f;     // NRLookMaxBrighten, 0 to 4 stops, 0 for no ceiling
  float max_darken = 0.0f;       // NRLookMaxDarken, 0 to 4 stops, 0 for no floor
  float max_colour = 0.0f;       // NRLookMaxColour, 0 to 2 stops, 0 for no limit

  // Whether the band split runs, whether a temporal filter runs, and whether anything runs.
  bool bands() const {
    return tone != 1.0f || detail != 1.0f || halo > 0.0f || halo_bright > 0.0f || stabilize != 0;
  }
  bool filtered() const { return stabilize != 0 || detail_stability != 1; }
  bool active() const {
    return bands() || filtered() || max_brighten > 0.0f || max_darken > 0.0f || max_colour > 0.0f;
  }
  // Whether the filter follows the motion estimate: the stabiliser's Motion mode, or detail
  // stability, which follows the motion where there is one.
  bool wants_motion() const { return stabilize == 2 || (stabilize == 0 && detail_stability != 1); }
};

inline bool same_look(const NrLook& a, const NrLook& b) {
  return a.tone == b.tone && a.detail == b.detail && a.detail_radius == b.detail_radius && a.halo == b.halo &&
         a.halo_bright == b.halo_bright && a.stabilize == b.stabilize && a.stabilize_ms == b.stabilize_ms &&
         a.stabilize_detail == b.stabilize_detail && a.detail_stability == b.detail_stability &&
         a.max_brighten == b.max_brighten && a.max_darken == b.max_darken && a.max_colour == b.max_colour &&
         a.keep_blacks == b.keep_blacks && a.motion_source == b.motion_source;
}
