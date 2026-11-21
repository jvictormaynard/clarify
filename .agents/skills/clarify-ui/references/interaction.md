# Check the interaction

- Begin with the user's goal. Complete it with the default and then change
  a choice. Check that Back, Cancel, and Discard preserve the right state.
- Try the longest supported label and translated copy in a small or short
  window. Scroll to the last control. Check that actions and errors remain
  reachable and that text stays legible.
- Use Tab and arrow keys where the control expects them. Check the visible
  focus ring, focus after closing an overlay, and focus during loading.
- Simulate failure, retry, and empty data. Keep the next step in the affected
  area. Use factual status and announce completion only after confirmation.
- On Windows and macOS use the platform's shortcut labels and window
  conventions. On iOS use native conventions for touch and navigation. Check
  the actual platform before claiming behavior that depends on its shell.

These checks adapt Emil's break-ui and apple-design guidance and taste-skill's
copy and browser checks. Record accepted preferences in the existing design
guide, following the project writing guidance.
