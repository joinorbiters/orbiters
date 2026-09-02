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

// jsdom implements no IntersectionObserver at all (unlike the pointer-capture gap
// above, not even a stub). landing/reveal.js gates every reveal on
// `typeof IntersectionObserver === 'function'` — deliberately, so a browser that
// lacks the API gets a fully visible page instead of one stuck hidden — but that
// means every test of reveal.js's default (non-stubbed) path would otherwise see
// the API as "absent" and never hide anything, which is indistinguishable from the
// bug the gate exists to avoid. Global and permanent: any future
// IntersectionObserver-gated code hits this identical jsdom gap.
if (typeof window.IntersectionObserver !== 'function') {
  window.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof IntersectionObserver
}

// The same jsdom gap, one API over: no ResizeObserver at all. `cmdk` (the command
// palette) constructs one unconditionally in an effect, so without this every test that
// mounts the palette dies with an uncaught `ReferenceError` instead of a failed
// assertion. Global and permanent, like the two stubs above: any future component that
// measures itself hits the identical gap.
if (typeof window.ResizeObserver !== 'function') {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}
