import { buildSlide } from "./deck_helpers.mjs";

export default async function slide01(presentation, ctx) {
  return buildSlide(presentation, ctx, 1);
}
