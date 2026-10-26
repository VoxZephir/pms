/** The assisted features: a model puts into words what Flask computed.
 *
 * Nothing here computes a figure: every number on screen comes from the
 * API, which also checked that each number the model wrote was in the facts
 * it was given. A GET shows what was already asked; only a button calls the
 * model. When no model is configured, these blocks are absent, and the
 * Corrections page says how to switch one on (`AiStatusNote`).
 *
 * One file per block, in `assist/`; this module names them for the pages. */
export * from "./assist/common";
export * from "./assist/Answer";
export * from "./assist/Merchants";
export * from "./assist/Month";
export * from "./assist/Savings";
export * from "./assist/Scenario";
