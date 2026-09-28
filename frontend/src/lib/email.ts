/** Opens the user's mail app with the request already written (subject + body). */
export function openEmail(subject: string, body: string, to = "") {
  // encodeURIComponent (not URLSearchParams, whose "+" for spaces mail apps show literally)
  const href = `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  window.location.href = href;
}

/** The standard document request sent to a client. */
export function documentRequest(subjectName: string | undefined, documents: string[]) {
  const subject = `Documents required: ${subjectName ?? "your file"}`;
  const body = [
    "Dear client,",
    "",
    "As part of our customer due diligence obligations, we kindly ask you to provide the following documents:",
    "",
    ...documents.map((d, i) => `${i + 1}. ${d}`),
    "",
    "Register extracts and proofs of address should be less than 3 months old, and copies certified where applicable.",
    "",
    "Thank you for your cooperation.",
    "Kind regards,",
  ].join("\n");
  return { subject, body };
}
