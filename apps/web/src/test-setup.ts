import '@testing-library/jest-dom/vitest'

// jsdom implements no pointer-capture API at all (not even a stub), but Radix UI's
// Select — DynamicFieldRenderer's `select` control — calls `hasPointerCapture` on
// every pointer interaction with its trigger, unconditionally. Without this, opening
// a Select under `userEvent.click` throws `target.hasPointerCapture is not a
// function` (reproduced directly: DynamicFieldRenderer.test.tsx's "offers every
// declared option for a select"), which is a gap in jsdom's coverage of the browser
// API, not a defect either component owns. Global and permanent, not scoped to that
// one test file: every future test of any Radix trigger (Select, Dropdown, ...)
// hits the identical gap.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {}
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {}
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
