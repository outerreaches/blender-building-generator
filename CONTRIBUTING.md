# Contributing

Thanks for your interest in contributing to the Procedural Building Shell Generator!

## Reporting Issues

If you find a bug or have a feature request, please open an issue. Include as much detail as possible:
- Blender version
- Add-on version (the `addon_version` custom property on a generated city collection or building)
- The operator, seed and settings you used: generation is deterministic, so they reproduce the result
- Steps to reproduce
- Screenshots or error logs

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Coding Standards

- Follow PEP 8 style guidelines
- Use type hints where possible
- Keep functions small and focused
- Document complex logic
- Keep the generator core free of Blender: only `__init__.py`, the operator and
  export modules, `building_assets.py`, `mesh_builder.py` and `util.py` import `bpy`
- Use a seeded `random.Random` rather than the global random state, so results stay deterministic
- Keep the geometry rules in [ARCHITECTURE.md](ARCHITECTURE.md): every element a closed solid,
  no same-facing coplanar faces

## License

By contributing, you agree that your contributions will be licensed under the GPL-3.0 License.
