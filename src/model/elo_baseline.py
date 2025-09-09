MODEL_VERSION = "0.0.1"

class ELO:
    def __init__(self, base=1500, k=32):
        self.base = base
        self.k = k
        self.ratings = {}

    def get(self, player):
        return self.ratings.get(player, self.base)

    def expected(self, ra, rb):
        return 1.0 / (1 + 10 ** ((rb - ra) / 400))

    def update(self, a, b, score_a):
        ra, rb = self.get(a), self.get(b)
        ea = self.expected(ra, rb)
        self.ratings[a] = ra + self.k * (score_a - ea)
        self.ratings[b] = rb + self.k * ((1 - score_a) - (1 - ea))
