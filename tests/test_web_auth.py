"""Tests for web UI auth module."""
import json
import tempfile
from pathlib import Path

import pytest

from pepperbot.channels.web.auth import (
    hash_password,
    verify_password,
    sign_session,
    verify_session,
    load_users,
    save_users,
    authenticate,
)


def test_hash_and_verify_correct_password():
    h = hash_password("mysecret")
    assert verify_password("mysecret", h) is True


def test_verify_wrong_password():
    h = hash_password("mysecret")
    assert verify_password("wrong", h) is False


def test_sign_and_verify_session():
    token = sign_session({"username": "oron"}, secret="abc123")
    payload = verify_session(token, secret="abc123")
    assert payload == {"username": "oron"}


def test_verify_tampered_session():
    token = sign_session({"username": "oron"}, secret="abc123")
    tampered = token[:-4] + "xxxx"
    assert verify_session(tampered, secret="abc123") is None


def test_verify_wrong_secret():
    token = sign_session({"username": "oron"}, secret="abc123")
    assert verify_session(token, secret="different") is None


def test_load_and_save_users(tmp_path):
    users_file = tmp_path / "users.json"
    users = [{"username": "oron", "password_hash": hash_password("pass")}]
    save_users(users, users_file)
    loaded = load_users(users_file)
    assert len(loaded) == 1
    assert loaded[0]["username"] == "oron"


def test_load_users_missing_file(tmp_path):
    users_file = tmp_path / "users.json"
    assert load_users(users_file) == []


def test_authenticate_valid(tmp_path):
    users_file = tmp_path / "users.json"
    h = hash_password("pass123")
    save_users([{"username": "oron", "password_hash": h}], users_file)
    assert authenticate("oron", "pass123", users_file) is True


def test_authenticate_invalid(tmp_path):
    users_file = tmp_path / "users.json"
    h = hash_password("pass123")
    save_users([{"username": "oron", "password_hash": h}], users_file)
    assert authenticate("oron", "wrongpass", users_file) is False


def test_authenticate_unknown_user(tmp_path):
    users_file = tmp_path / "users.json"
    save_users([], users_file)
    assert authenticate("nobody", "pass", users_file) is False
