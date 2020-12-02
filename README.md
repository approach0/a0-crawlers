## About

This is a collection of crawler scripts compatible to Approach Zero index feeder.

Historically it has been a subdirectory in Approach Zero search engine repository.
However, due to heavy image size from containerization process, it is split into an independent codebase to enable light-weight container running in low-end cloud nodes.

All scripts are specially written to crawl certain websites, for example, `crawler-math.stackexchange.com.py` is for Math StackExchange. Approach Zero inclines to use a set of "dedicated" crawlers instead of site-agnostic crawlers for better coverage and quality of corpus. Another advantage of doing in this way is being able to distribute work and track crawling process more efficiently.

The usage of any crawler script in this repo can be shown using `-h` or `--help` option, for instance
```sh
$ ./crawler-math.stackexchange.com.py -h
```

Welcome anyone to contribute their own crawler and submit to this repository. Each crawler should at least implement a `-h` or `--help` option to show help messages, and a targeting site range like `--begin-page` and `--end-page` for dividing workload.
