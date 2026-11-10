import { Icon } from "@/shared/ui";

/**
 * What each part of the review screen is for, shown by its "?" (Phase 6 §7.1). One home for the
 * words. Short: what the section is, then a line for each control whose name does not say it all.
 */

export const THINGS_TO_CHECK_HELP = (
  <>
    <span>Things worth a look before you approve. None of them stops you: approving records that you saw them.</span>
    <span>
      <strong>Show me</strong> opens the field it is about. <strong>Add signature</strong> lets you click on the
      document to put a signature there for that party.
    </span>
  </>
);

export const WHO_SIGNS_HELP = (
  <>
    <span>The people who fill in or sign this template, in signing order: signers first, then countersigners (your side).</span>
    <span>
      The <strong>pencil</strong> renames a party, changes how they sign, moves them up or down, or removes them.
      <strong> Filled in before sending</strong> is what you fill in yourself before it goes out.
    </span>
  </>
);

export const FIELDS_HELP = (
  <>
    <span>Every place someone fills in or signs. Choose one here, or its box on the document, to see it and change it.</span>
    <span>
      <strong>+ Add field</strong>: pick its type and who fills it, then click on the document where it goes, or drag to
      draw it. The buttons above filter by who fills a field.
    </span>
  </>
);

export const PLACES_HELP = (
  <>
    <span>
      Where this field appears on the document. One field can appear in several places (initials on every page); what
      is filled in once shows in all of them.
    </span>
    <span>
      <Icon name="plus" size={12} /> <strong>Add a place</strong>: click on the document to show this field there too.{" "}
      <Icon name="pages" size={12} /> <strong>On every page</strong>: the same spot on each page.{" "}
      <Icon name="split" size={12} /> <strong>Make separate field</strong>: the chosen place becomes a field of its own.{" "}
      <Icon name="close" size={12} /> <strong>Remove place</strong>: removes only the chosen place.
    </span>
    <span>The arrows move the chosen place a little; − and + make it smaller or larger.</span>
  </>
);

export const VERSIONS_HELP = (
  <>
    <span>Each version of this template, newest first: one per upload, and one each time an approved version is edited.</span>
    <span>
      <strong>Open</strong> shows it. The <strong>star</strong> makes an approved version the one new sends use.
      <strong> Find fields again</strong> asks the AI again and replaces that version&apos;s fields. The arrow downloads the
      original file.
    </span>
  </>
);
