def get_rank(rating: float) -> str:
    """レーティングルームのランク区分を返す"""
    if rating < 1000:
        return "E"
    if rating < 1300:
        return "N"
    if rating < 1600:
        return "Ex"
    if rating < 1900:
        return "H"
    if rating < 2200:
        return "L"
    return "Ph"
