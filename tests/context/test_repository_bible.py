# tests/context/test_repository_bible.py
import pytest
from storage.repository import Repository
from context.bible import BookBible, BibleUpdate


@pytest.fixture
def repo():
    r = Repository(db_path=":memory:")
    yield r
    r.close()


@pytest.fixture
def book_id(repo):
    return repo.create_book("El nombre del viento", "hash_bible_test")


class TestRepositoryBible:

    def test_get_bible_inexistente_devuelve_none(self, repo, book_id):
        assert repo.get_latest_bible(book_id) is None

    def test_save_y_get_bible(self, repo, book_id):
        bible = BookBible(
            glossary   = {"Kvothe": "Kvothe"},
            characters = {"Kvothe": "habla directo"},
            decisions  = ["tutear al lector"],
            last_scene = "Kvothe llegó.",
        )
        repo.save_bible(book_id, bible)
        recovered = repo.get_latest_bible(book_id)

        assert recovered.glossary["Kvothe"]   == "Kvothe"
        assert recovered.characters["Kvothe"] == "habla directo"
        assert "tutear al lector" in recovered.decisions

    def test_versionado_incrementa(self, repo, book_id):
        bible = BookBible.empty()

        v1 = repo.save_bible(book_id, bible)
        v2 = repo.save_bible(book_id, bible)
        v3 = repo.save_bible(book_id, bible)

        assert v1 == 1
        assert v2 == 2
        assert v3 == 3

    def test_get_latest_devuelve_version_mas_reciente(self, repo, book_id):
        bible_v1 = BookBible(last_scene="versión 1")
        bible_v2 = BookBible(last_scene="versión 2")

        repo.save_bible(book_id, bible_v1)
        repo.save_bible(book_id, bible_v2)

        latest = repo.get_latest_bible(book_id)
        assert latest.last_scene == "versión 2"

    def test_bibles_separadas_por_libro(self, repo):
        book_1 = repo.create_book("Libro A", "hash_a")
        book_2 = repo.create_book("Libro B", "hash_b")

        repo.save_bible(book_1, BookBible(last_scene="libro A"))
        repo.save_bible(book_2, BookBible(last_scene="libro B"))

        assert repo.get_latest_bible(book_1).last_scene == "libro A"
        assert repo.get_latest_bible(book_2).last_scene == "libro B"
