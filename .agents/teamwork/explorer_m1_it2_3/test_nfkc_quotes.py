import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8")

quotes_and_brackets = [
    # ASCII
    ('"', "ASCII double quote", 0x0022),
    ("'", "ASCII single quote", 0x0027),
    
    # Curly / Typographic Quotes
    ('“', "LEFT DOUBLE QUOTATION MARK", 0x201C),
    ('”', "RIGHT DOUBLE QUOTATION MARK", 0x201D),
    ('„', "DOUBLE LOW-9 QUOTATION MARK", 0x201E),
    ('‟', "DOUBLE HIGH-REVERSED-9 QUOTATION MARK", 0x201F),
    ('‘', "LEFT SINGLE QUOTATION MARK", 0x2018),
    ('’', "RIGHT SINGLE QUOTATION MARK", 0x2019),
    ('‚', "SINGLE LOW-9 QUOTATION MARK", 0x201A),
    ('‛', "SINGLE HIGH-REVERSED-9 QUOTATION MARK", 0x201B),
    ('«', "LEFT-POINTING DOUBLE ANGLE QUOTATION MARK", 0x00AB),
    ('»', "RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK", 0x00BB),
    ('‹', "SINGLE LEFT-POINTING ANGLE QUOTATION MARK", 0x2039),
    ('›', "SINGLE RIGHT-POINTING ANGLE QUOTATION MARK", 0x203A),
    ('″', "DOUBLE PRIME", 0x2033),
    ('′', "PRIME", 0x2032),

    # Fullwidth ASCII variants
    ('＂', "FULLWIDTH QUOTATION MARK", 0xFF02),
    ('＇', "FULLWIDTH APOSTROPHE", 0xFF07),

    # CJK Brackets and Quotation
    ('「', "LEFT CORNER BRACKET (kagi-kakko)", 0x300C),
    ('」', "RIGHT CORNER BRACKET", 0x300D),
    ('『', "LEFT WHITE CORNER BRACKET (nijukagi-kakko)", 0x300E),
    ('』', "RIGHT WHITE CORNER BRACKET", 0x300F),
    ('【', "LEFT BLACK LENTICULAR BRACKET (sumitsuki-kakko)", 0x3010),
    ('】', "RIGHT BLACK LENTICULAR BRACKET", 0x3011),
    ('〖', "LEFT WHITE LENTICULAR BRACKET", 0x3016),
    ('〗', "RIGHT WHITE LENTICULAR BRACKET", 0x3017),
    ('〔', "LEFT TORTOISE SHELL BRACKET (kikko-kakko)", 0x3014),
    ('〕', "RIGHT TORTOISE SHELL BRACKET", 0x3015),
    ('〈', "LEFT ANGLE BRACKET (yama-kakko)", 0x3008),
    ('〉', "RIGHT ANGLE BRACKET", 0x3009),
    ('《', "LEFT DOUBLE ANGLE BRACKET (nijuyama-kakko)", 0x300A),
    ('》', "RIGHT DOUBLE ANGLE BRACKET", 0x300B),

    # Fullwidth Parentheses / Brackets
    ('（', "FULLWIDTH LEFT PARENTHESIS", 0xFF08),
    ('）', "FULLWIDTH RIGHT PARENTHESIS", 0xFF09),
    ('［', "FULLWIDTH LEFT SQUARE BRACKET", 0xFF3B),
    ('］', "FULLWIDTH RIGHT SQUARE BRACKET", 0xFF3D),
    ('｛', "FULLWIDTH LEFT CURLY BRACKET", 0xFF5B),
    ('｝', "FULLWIDTH RIGHT CURLY BRACKET", 0xFF5D),
]

print(f"{'Char':<4} | {'Code':<6} | {'Name':<42} | {'NFKC Result':<12} | {'NFKC Code':<10} | {'NFKC Changed?'}")
print("-" * 90)
for char, name, codepoint in quotes_and_brackets:
    nfkc = unicodedata.normalize("NFKC", char)
    nfkc_codes = " ".join(f"U+{ord(c):04X}" for c in nfkc)
    changed = char != nfkc
    print(f"{char:<4} | U+{codepoint:04X} | {name:<42} | {nfkc:<12} | {nfkc_codes:<10} | {changed}")
