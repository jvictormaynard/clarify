import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import server_image_context as image_context


class ServerImageContextTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            ".dockerignore": b"**/.env*\n",
            "dictionary_snippets.py": b"# fixture\n",
            "server/.env.example": b"# public example only\n",
            "server/cloud/service/api.py": b"# fixture api\n",
            "server/cloud/service/groq.py": b"# fixture groq\n",
            "server/Dockerfile": b"FROM fixture\n",
        }
        self.files.update({f"shared/fixture-{i}.py": b"# fixture\n" for i in range(43)})

    def archive(self, files=None, *, source="a" * 40, extra=None):
        output = io.BytesIO()
        files = self.files if files is None else files
        with tarfile.open(
            fileobj=output,
            mode="w",
            format=tarfile.PAX_FORMAT,
            pax_headers={"comment": source},
        ) as archive:
            for name, value in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(value)
                archive.addfile(member, io.BytesIO(value))
            if extra is not None:
                archive.addfile(extra)
        return output.getvalue()

    def pin(self, data):
        return image_context.SourcePin(
            "a" * 40,
            hashlib.sha256(data).hexdigest(),
            49,
            {
                name: hashlib.sha256(self.files[name]).hexdigest()
                for name in (
                    "server/cloud/service/api.py",
                    "server/cloud/service/groq.py",
                )
            },
        )

    def test_verified_archive_preserves_all_49_sources(self):
        data = self.archive()
        self.assertEqual(image_context.archive_files(data, self.pin(data)), self.files)

    def test_modified_archive_is_rejected(self):
        data = self.archive()
        pin = self.pin(data)
        with self.assertRaises(ValueError):
            image_context.archive_files(data + b"changed", pin)

    def test_archive_from_another_commit_is_rejected(self):
        data = self.archive(source="b" * 40)
        with self.assertRaises(ValueError):
            image_context.archive_files(data, self.pin(data))

    def test_traversal_and_private_paths_are_rejected_even_with_a_matching_hash(self):
        for name in (
            "../outside",
            "/outside",
            "server/../outside",
            "server/.env",
            "server/config.json",
            "shared/recordings/clip.wav",
            "server\\secret.py",
        ):
            with self.subTest(name=name):
                files = {**self.files}
                files.pop("shared/fixture-0.py")
                files[name] = b"private"
                data = self.archive(files)
                with self.assertRaises(ValueError):
                    image_context.archive_files(data, self.pin(data))

    def test_extra_file_symlink_and_duplicate_are_rejected(self):
        files = {**self.files, "server/extra.py": b"extra"}
        data = self.archive(files)
        with self.assertRaises(ValueError):
            image_context.archive_files(data, self.pin(data))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.REGTYPE):
            with self.subTest(kind=kind):
                member = tarfile.TarInfo("shared/fixture-0.py")
                member.type = kind
                member.linkname = "/outside"
                data = self.archive(extra=member)
                with self.assertRaises(ValueError):
                    image_context.archive_files(data, self.pin(data))

    def test_modified_critical_file_is_rejected(self):
        files = {**self.files, "server/cloud/service/api.py": b"changed"}
        data = self.archive(files)
        with self.assertRaises(ValueError):
            image_context.archive_files(data, self.pin(data))

    def test_preparation_uses_only_the_verified_archive_and_separates_manifest(self):
        data = self.archive()
        pin = self.pin(data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text("DO_NOT_COPY=fixture")
            context, manifest = root / "context", root / "manifest.json"
            with patch.object(image_context, "git_archive", return_value=data):
                value = image_context.prepare(root, context, manifest, pin)
                self.assertEqual(
                    image_context.validated_manifest(root, manifest, pin), value
                )
            image_context.verify_tree(context, value["files"])
            self.assertEqual(len(value["files"]), 49)
            self.assertEqual(len(value["image_files"]), 47)
            self.assertIn("server/.env.example", value["files"])
            self.assertNotIn("server/.env.example", value["image_files"])
            self.assertNotIn(".dockerignore", value["image_files"])
            self.assertFalse((context / ".env").exists())

    def test_invalid_archive_leaves_no_context_or_manifest(self):
        data = self.archive()
        pin = self.pin(data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                image_context, "git_archive", return_value=data + b"changed"
            ):
                with self.assertRaises(ValueError):
                    image_context.prepare(
                        root, root / "context", root / "manifest.json", pin
                    )
            self.assertEqual(list(root.iterdir()), [])

    def test_context_and_manifest_tampering_are_rejected(self):
        data = self.archive()
        pin = self.pin(data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, path = root / "context", root / "manifest.json"
            with patch.object(image_context, "git_archive", return_value=data):
                manifest = image_context.prepare(root, context, path, pin)
                changed = json.loads(path.read_text())
                changed["files"]["shared/fixture-1.py"] = "0" * 64
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    image_context.validated_manifest(root, path, pin)
            for name in ("shared/fixture-1.py", "server/extra.py"):
                with self.subTest(name=name):
                    target = context / name
                    prior = target.read_bytes() if target.exists() else None
                    target.write_bytes(b"changed")
                    with self.assertRaises(ValueError):
                        image_context.verify_tree(context, manifest["files"])
                    if prior is None:
                        target.unlink()
                    else:
                        target.write_bytes(prior)

    def test_context_symlink_is_rejected(self):
        data = self.archive()
        pin = self.pin(data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = root / "context"
            with patch.object(image_context, "git_archive", return_value=data):
                manifest = image_context.prepare(
                    root, context, root / "manifest.json", pin
                )
            target = context / "shared/fixture-0.py"
            target.unlink()
            try:
                target.symlink_to(root / "outside")
            except OSError:
                self.skipTest("Host cannot create an isolated symlink")
            with self.assertRaises(ValueError):
                image_context.verify_tree(context, manifest["files"])

    def test_image_copy_hashes_and_cleanup_are_checked_without_docker(self):
        image = (
            image_context.IMAGE_REPOSITORY
            + ":recovery-"
            + image_context.PIN.source
            + "-123-1"
        )
        expected = {"shared/a.py": hashlib.sha256(b"expected").hexdigest()}
        container = "f" * 64
        for content in (b"expected", b"changed"):
            with self.subTest(content=content):

                def docker(*args):
                    if args[0] == "create":
                        return container
                    if args[0] == "cp":
                        destination = Path(args[2]) / "app/shared"
                        destination.mkdir(parents=True)
                        (destination / "a.py").write_bytes(content)
                    return ""

                with patch.object(
                    image_context, "_docker", side_effect=docker
                ) as command:
                    if content == b"expected":
                        image_context.verify_image(image, expected)
                    else:
                        with self.assertRaises(ValueError):
                            image_context.verify_image(image, expected)
                self.assertEqual(command.call_args.args, ("rm", "-f", container))

    def test_image_reference_and_published_digest_cannot_change_namespace(self):
        image = (
            image_context.IMAGE_REPOSITORY
            + ":recovery-"
            + image_context.PIN.source
            + "-123-1"
        )
        with patch.object(image_context, "_docker") as command:
            with self.assertRaises(ValueError):
                image_context.verify_image(
                    image.replace("jvictormaynard", "other-owner"), {}
                )
        command.assert_not_called()
        manifest = {
            "source": image_context.PIN.source,
            "archive_sha256": image_context.PIN.archive_sha256,
            "files": dict.fromkeys(self.files, "f" * 64),
            "image_files": dict.fromkeys(
                set(self.files) - image_context.IMAGE_OMISSIONS, "f" * 64
            ),
        }
        digest = image_context.IMAGE_REPOSITORY + "@sha256:" + "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(manifest))
            with patch.object(
                image_context,
                "_docker",
                side_effect=[json.dumps([digest]), "sha256:" + "b" * 64, "linux/amd64"],
            ):
                result = image_context.record_image(image, manifest, path, "c" * 40)
            self.assertEqual(result["digest_reference"], digest)
            self.assertEqual(result["source_files"], 49)
            self.assertEqual((result["os"], result["architecture"]), ("linux", "amd64"))
            for candidates in (
                [],
                [digest, digest],
                [digest.replace("jvictormaynard", "other-owner")],
            ):
                with (
                    self.subTest(candidates=candidates),
                    patch.object(
                        image_context, "_docker", return_value=json.dumps(candidates)
                    ),
                ):
                    with self.assertRaises(ValueError):
                        image_context.record_image(image, manifest, path, "c" * 40)

    def test_image_metadata_rejects_wrong_or_missing_platform(self):
        image = (
            image_context.IMAGE_REPOSITORY
            + ":recovery-"
            + image_context.PIN.source
            + "-123-1"
        )
        digest = image_context.IMAGE_REPOSITORY + "@sha256:" + "a" * 64
        manifest = {
            "source": image_context.PIN.source,
            "archive_sha256": image_context.PIN.archive_sha256,
            "files": {},
            "image_files": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(manifest))
            for platform in ("linux/arm64", "", "linux/", "/amd64", "windows/amd64"):
                with (
                    self.subTest(platform=platform),
                    patch.object(
                        image_context,
                        "_docker",
                        side_effect=[
                            json.dumps([digest]),
                            "sha256:" + "b" * 64,
                            platform,
                        ],
                    ),
                ):
                    with self.assertRaises(ValueError):
                        image_context.record_image(image, manifest, path, "c" * 40)


if __name__ == "__main__":
    unittest.main()
