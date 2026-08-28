# Line Item BBox Highlighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show review-screen image highlights for each `line_items[].bbox`, with the currently focused line item emphasized.

**Architecture:** Keep OCR optional and non-fatal. When OCR grounding is enabled, derive missing line-item boxes from `OcrLayer.words` by grouping OCR words into text-line candidates, requiring a unique strong description-token match, then storing the result on the existing `line_items.bbox` JSON column. The frontend types the existing API field, filters malformed boxes at render time, and draws boxes in the same transformed image stage as the receipt photo.

**Tech Stack:** Python pipeline and pytest; React 19, TypeScript, CSS modules, Vitest.

---

### File Structure

- Modify `src/receipts/pipeline.py`: carry the OCR layer through preprocessing and apply conservative bbox derivation to `outcome.extraction` before scoring/persisting.
- Modify `tests/test_process_receipt.py`: add focused tests proving OCR word boxes become stored line-item boxes, unmatched/ambiguous rows stay null, and malformed OCR geometry cannot fail the receipt.
- Modify `frontend/src/api/types.ts`: add the normalized bbox type to `LineItem`.
- Modify `frontend/src/review/ImagePane.tsx`: accept line-item boxes and active position, filter invalid boxes, and render an overlay in image coordinates.
- Modify `frontend/src/review/ImagePane.module.css`: add stage and highlight overlay rules.
- Modify `frontend/src/review/LineItemsTable.tsx`: expose focused row position to `ReviewScreen` while keeping the existing row highlight.
- Modify `frontend/src/review/ReviewScreen.tsx`: lift active line item state and pass boxes to `ImagePane`.
- Modify frontend tests in `frontend/tests/*.test.tsx`: pin active-row-to-image highlighting and bbox filtering.
- Modify `frontend/tests/stylesheets.test.ts`: update the CSS census for the new overlay declarations.
- Modify `IMPLEMENTATION_PLAN.md`: check the task only after backend/frontend tests pass.

### Task 1: Backend OCR BBox Derivation

**Files:**
- Modify: `src/receipts/pipeline.py`
- Test: `tests/test_process_receipt.py`

- [x] **Step 1: Write the failing pipeline test**

Add a reader fixture with `.text` and `.words`, process a receipt with OCR grounding enabled, then assert the stored row for `RICE 5KG` has the union of matching OCR word boxes while an unmatched row keeps `bbox is None`.

- [x] **Step 2: Run the focused test and confirm it fails**

Run: `python -m pytest tests/test_process_receipt.py -q --basetemp .tmp_pytest -p no:cacheprovider`

Expected: fail because `_ground_in_ocr` drops `layer.words` and nothing assigns item `bbox`.

- [x] **Step 3: Implement conservative bbox derivation**

Add helpers that tokenize OCR words and item descriptions with `normalize_desc`, group words into OCR text-line candidates, require a unique strong token overlap, and assign only missing item boxes. Leave model-provided bboxes untouched; omit ambiguous or malformed geometry.

- [x] **Step 4: Re-run the focused backend test**

Run: `python -m pytest tests/test_process_receipt.py -q --basetemp .tmp_pytest -p no:cacheprovider`

Expected: pass.

### Task 2: Frontend Typed Overlay

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/review/ImagePane.tsx`
- Modify: `frontend/src/review/ImagePane.module.css`
- Modify: `frontend/tests/image-pane.test.tsx`
- Modify: `frontend/tests/stylesheets.test.ts`

- [x] **Step 1: Write failing ImagePane tests**

Add tests proving:

- a valid bbox renders as an overlay with percentage geometry;
- the active item has the active overlay class/label;
- malformed boxes do not render;
- zoom/rotate apply to the shared image stage.

- [x] **Step 2: Run the focused frontend test and confirm it fails**

Run: `npm.cmd test -- tests/image-pane.test.tsx`, from `frontend/`.

Expected: fail because `ImagePane` has no bbox props and no overlay DOM.

- [x] **Step 3: Implement the overlay**

Add `NormalizedBBox`/`LineItem.bbox`, render a `.stage` wrapper around the image, move transform to the stage, and position `.highlight` spans as percentages inside an `aria-hidden` overlay. Filter invalid geometry by shape, finite numbers, range, and positive width/height.

- [x] **Step 4: Update the CSS census**

Run the stylesheet guard once to read its diff, update `CENSUS['review/ImagePane.module.css']`, then re-run it.

### Task 3: ReviewScreen Row Focus Wiring

**Files:**
- Modify: `frontend/src/review/LineItemsTable.tsx`
- Modify: `frontend/src/review/ReviewScreen.tsx`
- Modify: `frontend/tests/receipt-form.test.tsx`
- Modify: `frontend/tests/review-screen.test.tsx`
- Modify other frontend fixtures that need `bbox`.

- [x] **Step 1: Write failing row-focus integration tests**

In `review-screen.test.tsx`, load a receipt with a line item carrying a bbox, focus one of that row's fields, and assert the image overlay for that line item becomes active.

- [x] **Step 2: Run the focused tests and confirm they fail**

Run: `npm.cmd test -- tests/review-screen.test.tsx tests/receipt-form.test.tsx`, from `frontend/`.

Expected: fail because focus state does not leave `LineItemsTable`.

- [x] **Step 3: Lift active row state**

Add optional `activePosition` and `onActivePositionChange` props to `LineItemsTable`, keep the existing internal fallback for standalone use, and have `ReviewScreen` own the active position for the claimed receipt.

- [x] **Step 4: Re-run focused frontend tests**

Run: `npm.cmd test -- tests/image-pane.test.tsx tests/review-screen.test.tsx tests/receipt-form.test.tsx`, from `frontend/`.

Expected: pass.

### Task 4: Verification and Task Checkbox

**Files:**
- Modify: `IMPLEMENTATION_PLAN.md`

- [x] **Step 1: Run focused backend and frontend verification**

Run:

```powershell
python -m pytest tests/test_process_receipt.py tests/test_api_read.py -q --basetemp .tmp_pytest -p no:cacheprovider
cd frontend
npm.cmd test -- tests/image-pane.test.tsx tests/review-screen.test.tsx tests/receipt-form.test.tsx tests/stylesheets.test.ts tests/no-float-in-money-path.test.ts
npm.cmd run typecheck
npm.cmd run lint
```

- [x] **Step 2: Update the implementation checkbox**

If the checks pass, change the task in `IMPLEMENTATION_PLAN.md` from unchecked to checked and replace the stale "highlighting is not built" note with a dated summary of the backend bbox derivation and frontend overlay.

- [x] **Step 3: Review the final diff**

Run: `git diff --check` and `git status --short`.

Expected: only the files named in this plan, plus pre-existing unrelated repair-eval changes.
