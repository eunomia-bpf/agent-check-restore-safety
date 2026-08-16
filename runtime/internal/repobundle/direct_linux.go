package repobundle

import "golang.org/x/sys/unix"

// openDirectDirectory opens an absolute directory while atomically rejecting
// every symbolic-link or procfs magic-link component in its path.
func openDirectDirectory(path string) (int, error) {
	return unix.Openat2(unix.AT_FDCWD, path, &unix.OpenHow{
		Flags:   uint64(unix.O_RDONLY | unix.O_DIRECTORY | unix.O_CLOEXEC),
		Resolve: unix.RESOLVE_NO_SYMLINKS | unix.RESOLVE_NO_MAGICLINKS,
	})
}
