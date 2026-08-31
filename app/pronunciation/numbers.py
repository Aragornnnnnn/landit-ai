# 숫자 단어를 발화 형태(영어 철자)로 바꾸는 모듈
#
# 자산 생성 스크립트가 "9" 같은 숫자 단어의 발화 철자("nine") 표기를 만들 때 쓴다.
# 판정·억양 확인에서는 숫자 단어를 제외하고 항상 CORRECT로 처리한다.
_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = {
    2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
    6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety",
}


def is_numeric_word(word: str) -> bool:
    return word.strip().isdigit()


def spell_out(word: str) -> str | None:
    """0~99 숫자를 영어 철자로 바꾼다. 범위 밖이면 None."""
    stripped = word.strip()
    if not stripped.isdigit():
        return None
    value = int(stripped)
    if value < 20:
        return _ONES[value] if value < len(_ONES) else None
    if value < 100:
        tens, ones = divmod(value, 10)
        return _TENS[tens] if ones == 0 else f"{_TENS[tens]} {_ONES[ones]}"
    return None
