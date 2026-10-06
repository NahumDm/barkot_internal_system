import { configure } from "@testing-library/dom";

import "@testing-library/jest-dom/vitest";

/**
 * A second for a two-request render is a comfortable budget on an idle
 * machine, and a lie on one that is also running a database and a browser.
 * The screens under test await a session check before they ask for anything, so
 * a loaded CPU turns a correct screen into a reported failure. Three seconds
 * still fails quickly for a genuine hang and keeps a slow machine out of the
 * verdict.
 */
configure({ asyncUtilTimeout: 3000 });
