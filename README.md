## About

This is a collection of crawler scripts compatible to Approach Zero index feeder.

Historically it has been a subdirectory in Approach Zero search engine repository.
However, due to heavy image size from containerization process, it is split into an independent codebase to enable light-weight container running in low-end cloud nodes.

All scripts are specially written to crawl specific websites, for example, `crawler-stackexchange.py` is for StackExchange sites.

The usage of any crawler script in this repo can be shown using `-h` or `--help` option, for instance
```sh
$ ./crawler-stackexchange.py -h
```

We find it useful to implement "dedicated" crawlers instead of site-agnostic crawlers for better coverage and quality of corpus. Another advantage of doing in this way is being able to distribute work and track crawling process more efficiently.

Welcome anyone to contribute their own crawler and submit to this repository. Each crawler should at least implement a `-h` or `--help` option to show help messages, and a targeting site range like `--begin-page` and `--end-page` for dividing workload.
