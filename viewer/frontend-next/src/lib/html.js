import { createElement } from "../../vendor/react.js";
import htm from "../../vendor/htm.js";

/** JSX-free templates: `html\`<p>${x}</p>\`` renders through React.createElement. */
export const html = htm.bind(createElement);
