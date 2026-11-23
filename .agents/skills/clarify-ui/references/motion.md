# Use motion when it helps

- Name the state change that motion explains. Remove motion that delays
  repeated actions, obscures content, or competes with feedback. Keep immediate
  feedback for capture, progress, or completion where it helps.
- Reuse the existing motion tokens and reduced motion handling. Verify
  interruption and rapid repetition. In reduced motion, the final state and
  next action must still be clear.
- Prefer opacity and transforms when layout does not have to change. Measure
  affected rendering if there is jank. Look for layout work, extra renders, or
  animation that keeps running when hidden before adding more code.
- On Expo, reuse the animation tools already in the feature. Select native
  Animated or Reanimated based on the interaction and validate on the device.

These checks adapt Emil's animate, remove-animations, animation-performance,
review-animations, and animate-expo guidance. The Clarify design guide owns
the appearance and timing of each shared control.
