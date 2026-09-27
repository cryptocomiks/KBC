"""Temporary probe: Find Case Law query forms."""

import re

import httpx

with httpx.Client(timeout=40, follow_redirects=True) as c:
    for params in ({"party": "Carillion"}, {"query": '"Carillion"'}, {"query": "Carillion"}, {"party": "Carillion PLC"}):
        r = c.get("https://caselaw.nationalarchives.gov.uk/atom.xml", params=params)
        titles = re.findall(r"<entry><title>(.*?)</title>", r.text)
        print(params, r.status_code, len(titles), titles[:6])
