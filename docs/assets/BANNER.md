# README banner

`readme.md` shows `banner-dark.png` on GitHub's dark theme and `banner-light.png` on the light one (`<picture>`).
The files in the repository are plain placeholders: replace them with the generated images **keeping the same
names**, size about **1600 × 400** (4:1), PNG, under 1 MB each.

## Gemini prompt (attach the assistant picture as the subject reference)

**1. Dark version**

```
Use the attached image as the subject reference: keep the same character, face, hairstyle and outfit, faithful to the reference.

Create an ultra-wide website banner (21:9, it will be cropped to 4:1, keep everything important inside the central horizontal band).

Style: minimalist, elegant, calm, premium tech product. Dark theme.
Background: deep near-black (#0B0D12) with a very soft, warm amber glow behind the subject, like the light of a home hearth, fading into darkness. Plenty of empty negative space. No patterns, no clutter, no extra objects, no text other than the title.
Subject: the character from the reference, half-body, placed in the right third, softly lit by the warm glow from one side, gentle rim light, looking slightly toward the left (toward the title).
Title on the left third, vertically centered: the word "HESTIA" in a thin, wide, geometric sans-serif, uppercase, generous letter spacing, warm off-white (#ECE8E0). Under it, smaller and in muted grey: "your personal assistant, at home".
Color palette: near-black, warm amber (#C07A3A) as the only accent, off-white. Smooth gradients, subtle film grain, high resolution, crisp edges.
```

**2. Light version** (in the same conversation, right after the dark one)

```
Now make the light-theme version of exactly this banner: same composition, same character, same pose, same title and subtitle in the same place.
Background: warm off-white (#F6F4F0) with a very soft peach/amber glow (#F8D9B8) behind the subject.
Title in near-black charcoal (#1C1E24), subtitle in medium grey. Keep it just as minimalist and airy, no extra elements.
```

Tips: if the face drifts from the reference, add «keep the face identical to the reference image». If the text
comes out wrong, ask for the banner **without any text** and the README still works (the tagline is right under
the banner).
